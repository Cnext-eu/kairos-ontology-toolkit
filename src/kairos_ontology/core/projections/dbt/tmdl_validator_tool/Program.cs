// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Cnext.eu
//
// One argument: a folder containing a TMDL "definition" tree (database.tmdl,
// model.tmdl, tables/*.tmdl, ...). Deserializes it with the same TOM SDK engine
// Power BI Desktop / Fabric use, and prints one line of JSON to stdout:
//   {"status":"pass","table_count":N}
//   {"status":"fail","error_type":"...","message":"..."}
// Exit code 0 on pass, 1 on fail, 2 on usage error. Never talks to a live Power BI
// workspace or Fabric tenant -- this is a pure local file-structure/syntax check.

using Microsoft.AnalysisServices.Tabular;
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
}
catch (Exception ex)
{
    result["status"] = "fail";
    result["error_type"] = ex.GetType().Name;
    result["message"] = ex.Message;
}

Console.WriteLine(JsonSerializer.Serialize(result));
return (string?)result["status"] == "pass" ? 0 : 1;
