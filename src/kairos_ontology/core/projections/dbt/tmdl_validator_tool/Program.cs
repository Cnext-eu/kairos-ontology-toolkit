// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Cnext.eu
//
// One argument: a folder containing a TMDL "definition" tree (database.tmdl,
// model.tmdl, tables/*.tmdl, ...). Deserializes it with the same TOM SDK engine
// Power BI Desktop / Fabric use, and prints one line of JSON to stdout:
//   {"status":"pass","table_count":N,"tables":[{"name":..,"column_count":N,"measure_count":N}],
//    "relationship_count":N}
//   {"status":"fail","error_type":"...","message":"..."}
//   {"status":"unavailable","error_type":"...","message":"..."}
// Exit code 0 on pass, 1 on fail, 2 on usage error, 3 on unavailable. Never talks to a
// live Power BI workspace or Fabric tenant -- this is a pure local file-structure/
// syntax check.

using Microsoft.AnalysisServices.Tabular;
using Microsoft.AnalysisServices.Tabular.Tmdl;
using JsonSerializer = System.Text.Json.JsonSerializer;

if (args.Length < 1)
{
    Console.Error.WriteLine("usage: TmdlValidator <definition-folder>");
    return 2;
}

var result = new Dictionary<string, object?>();
try
{
    var database = TmdlSerializer.DeserializeDatabaseFromFolder(args[0]);
    result["status"] = "pass";
    result["table_count"] = database.Model.Tables.Count;
    // The inventory, not only the count. The count alone answers "did anything parse";
    // the read-path cross-check (issue #879) has to answer "which tables and measures
    // did our own parser not see", which is the difference between a warning a reader
    // can act on and one they can only worry about.
    result["tables"] = database.Model.Tables.Select(table => new Dictionary<string, object?>
    {
        ["name"] = table.Name,
        ["column_count"] = table.Columns.Count,
        ["measure_count"] = table.Measures.Count,
    }).ToList();
    result["relationship_count"] = database.Model.Relationships.Count;
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
