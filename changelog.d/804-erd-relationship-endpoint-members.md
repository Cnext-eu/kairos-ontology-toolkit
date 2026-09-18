### Fixed
- **An imported class reached only by a relationship now shows its attributes (issue
  #804).** `project --target erd` drew every non-local class as a member-less stub. That
  is right for an inheritance ancestor — its attributes are already listed, prefixed `#`,
  on the classes that inherit them — but wrong for a class reached only across an object
  property, because nothing inherits from it and its attributes then appeared nowhere in
  the diagram at all. On one hub that hid `vesselName`, `imoNumber`, `draftValue` and
  every certificate, survey and crew-list class hanging off `imo:Vessel`. A class that is
  both an ancestor and an endpoint still renders as a stub, and every imported class keeps
  the stereotype naming the model it comes from.
