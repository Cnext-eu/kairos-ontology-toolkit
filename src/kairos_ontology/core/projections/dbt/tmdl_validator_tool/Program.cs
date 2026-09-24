// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Cnext.eu
//
// Usage: TmdlValidator <definition-folder> [--inventory]
//
// Deserializes a TMDL "definition" tree (database.tmdl, model.tmdl, tables/*.tmdl, ...)
// with the same TOM SDK engine Power BI Desktop / Fabric use, and prints one line of
// JSON to stdout:
//   {"status":"pass","table_count":N,"tables":[{"name":..,"column_count":N,"measure_count":N}],
//    "relationship_count":N}
//   {"status":"fail","error_type":"...","message":"..."}
//   {"status":"unavailable","error_type":"...","message":"..."}
// With --inventory a pass also carries "model": the full reading import-tmdl consumes
// (#879) -- tables with columns, measures, partitions and annotations; relationships
// with their endpoints; model properties. Enum values are emitted by name and mapped to
// TMDL spellings on the Python side.
// Exit code 0 on pass, 1 on fail, 2 on usage error, 3 on unavailable. Never talks to a
// live Power BI workspace or Fabric tenant -- this is a pure local file read.

using Microsoft.AnalysisServices.Tabular;
using Microsoft.AnalysisServices.Tabular.Tmdl;
using JsonSerializer = System.Text.Json.JsonSerializer;

if (args.Length < 1)
{
    Console.Error.WriteLine("usage: TmdlValidator <definition-folder> [--inventory]");
    return 2;
}

var inventory = args.Skip(1).Contains("--inventory");

// Each TOM object has its own annotation collection type; all of them enumerate
// Annotation, so one helper covers tables, columns and measures.
static Dictionary<string, string> Annotations(IEnumerable<Annotation> annotations) =>
    annotations.ToDictionary(item => item.Name, item => item.Value ?? "");

var result = new Dictionary<string, object?>();
try
{
    var database = TmdlSerializer.DeserializeDatabaseFromFolder(args[0]);
    var model = database.Model;
    result["status"] = "pass";
    result["table_count"] = model.Tables.Count;
    // The inventory, not only the count. The count alone answers "did anything parse";
    // the read-path cross-check (issue #879) has to answer "which tables and measures
    // did our own parser not see", which is the difference between a warning a reader
    // can act on and one they can only worry about.
    result["tables"] = model.Tables.Select(table => new Dictionary<string, object?>
    {
        ["name"] = table.Name,
        ["column_count"] = table.Columns.Count(c => c.Type != ColumnType.RowNumber),
        ["measure_count"] = table.Measures.Count,
    }).ToList();
    result["relationship_count"] = model.Relationships.Count;

    if (inventory)
    {
        result["model"] = new Dictionary<string, object?>
        {
            ["name"] = model.Name,
            ["compatibility_level"] = database.CompatibilityLevel,
            ["default_mode"] = model.DefaultMode.ToString(),
            ["culture"] = model.Culture,
            ["tables"] = model.Tables.Select(table => new Dictionary<string, object?>
            {
                ["name"] = table.Name,
                ["lineage_tag"] = table.LineageTag,
                ["description"] = table.Description,
                ["is_hidden"] = table.IsHidden,
                ["annotations"] = Annotations(table.Annotations),
                // RowNumber is TOM's internal per-table column; TMDL never declares it.
                ["columns"] = table.Columns.Where(c => c.Type != ColumnType.RowNumber)
                    .Select(column => new Dictionary<string, object?>
                    {
                        ["name"] = column.Name,
                        ["data_type"] = column.DataType.ToString(),
                        ["format_string"] = column.FormatString,
                        ["source_column"] = (column as DataColumn)?.SourceColumn,
                        ["expression"] = (column as CalculatedColumn)?.Expression,
                        ["is_hidden"] = column.IsHidden,
                        ["lineage_tag"] = column.LineageTag,
                        ["description"] = column.Description,
                        ["is_key"] = column.IsKey,
                        ["display_folder"] = column.DisplayFolder,
                        ["annotations"] = Annotations(column.Annotations),
                    }).ToList(),
                ["measures"] = table.Measures.Select(measure => new Dictionary<string, object?>
                {
                    ["name"] = measure.Name,
                    ["expression"] = measure.Expression,
                    ["format_string"] = measure.FormatString,
                    ["description"] = measure.Description,
                    ["display_folder"] = measure.DisplayFolder,
                    ["lineage_tag"] = measure.LineageTag,
                    ["is_hidden"] = measure.IsHidden,
                    ["annotations"] = Annotations(measure.Annotations),
                }).ToList(),
                ["partitions"] = table.Partitions.Select(partition => new Dictionary<string, object?>
                {
                    ["name"] = partition.Name,
                    ["mode"] = partition.Mode.ToString(),
                    ["source_type"] = partition.SourceType.ToString(),
                }).ToList(),
            }).ToList(),
            ["relationships"] = model.Relationships.Select(relationship =>
            {
                var single = relationship as SingleColumnRelationship;
                return new Dictionary<string, object?>
                {
                    ["name"] = relationship.Name,
                    ["from_table"] = relationship.FromTable?.Name,
                    ["from_column"] = single?.FromColumn?.Name,
                    ["to_table"] = relationship.ToTable?.Name,
                    ["to_column"] = single?.ToColumn?.Name,
                    ["from_cardinality"] = single?.FromCardinality.ToString(),
                    ["to_cardinality"] = single?.ToCardinality.ToString(),
                    ["cross_filtering"] = relationship.CrossFilteringBehavior.ToString(),
                    ["is_active"] = relationship.IsActive,
                };
            }).ToList(),
        };
    }
}
catch (TmdlFormatException ex)
{
    // The TMDL text itself is malformed -- TmdlSerializer's own parser rejected it.
    result["status"] = "fail";
    result["error_type"] = ex.GetType().Name;
    result["message"] = ex.Message;
}
catch (TmdlSerializationException ex)
{
    // The text parses but the model does not hold together: an unresolvable
    // relationship endpoint, a ref to a table the tree does not contain. TOM raises
    // this about the CONTENT, so it is a validation failure, not an environment one.
    // Power BI Desktop refuses to open such a model (issue #876).
    result["status"] = "fail";
    result["error_type"] = ex.GetType().Name;
    result["message"] = ex.Message;
}
catch (Exception ex)
{
    // Anything else (e.g. TypeInitializationException from
    // Microsoft.AnalysisServices.Hosting.ClientHostingManager, seen under concurrent
    // cold starts on some platforms) means the SDK itself could not run here, not
    // that the TMDL is invalid -- never misreport an environment limitation as a
    // content failure.
    result["status"] = "unavailable";
    result["error_type"] = ex.GetType().Name;
    result["message"] = ex.Message;
}

Console.WriteLine(JsonSerializer.Serialize(result));
return (string?)result["status"] switch
{
    "pass" => 0,
    "fail" => 1,
    _ => 3,
};
