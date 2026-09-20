### Fixed
- **A structurally broken Power BI model now fails TMDL validation instead of reporting
  as unvalidatable.** The bundled TOM validator treated every exception except
  `TmdlFormatException` as "the SDK could not run here". But `TmdlSerializationException`
  is raised about the *content* — a relationship endpoint pointing at a table or column
  the model does not contain — and that is exactly the defect that makes Power BI Desktop
  refuse to open a PBIP. Because `emit-gold` only fails on `status == "fail"`, such a
  model emitted green with its diagnostic printed as a parenthetical aside worded
  identically to "you don't have the .NET SDK installed". Serialization failures are now
  reported as validation failures; genuine environment problems still report as
  unavailable.
