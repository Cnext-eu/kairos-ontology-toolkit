# Core concepts and how they relate

A reference for the concepts the global data warehouse models, how they connect, and what each one is called in CargoWise and in the industry reference models.

**Grounded in:** the global team workshop (`.import/businessdiscovery/customerinput/workshop/globalteamsession.transcript`) for the business meaning, and the hub's 36 authored EntityBindings for the mapping. Every relationship listed here is authored and compiles; every CargoWise table name is one a binding or `int_` model actually reads.

This document describes what exists and how it fits together. Known gaps are deliberately out of scope — see [cargowise-model-workshop-fitgap.md](cargowise-model-workshop-fitgap.md).


---

## Three vocabularies, one concept

The workshop's central requirement is that the model must survive being pointed at other systems:

> "The target data model must express common business concepts independently of CargoWise so that data from approximately 23 current TMSs… can be mapped into one model. Source-specific names, identifiers, and structures must be handled through mappings rather than embedded in the business vocabulary."

So every concept has three names, and they are deliberately different:

| Layer | Example | Where it lives |
|-------|---------|----------------|
| **Source** | `jobshipment` (`JS_UniqueConsignRef`) | CargoWise; changes per TMS |
| **Canonical** | `consignment:``HouseConsignmentRecord` | our ontology; one per concept |
| **Industry** | `mmt:HouseConsignment` | the reference model we inherit from |

The canonical class is a *specialisation* of the industry class — `HouseConsignmentRecord` `rdfs:subClassOf` `mmt:HouseConsignment` `rdfs:subClassOf` `mmt:Consignment`. Fracht-specific attributes hang off ours; anything standard is inherited.


---

# 1. The transport spine

## How it flows

The workshop states the operational sequence plainly:

> "The usual flow begins with a client transport order, followed by creation of one or more shipments or house consignments. Shipments may be consolidated into a JobConsol or master consignment, with multiple client consignments attached to one master when routing, deadlines, and operational circumstances allow."

```
Transport order ──creates──▶ House consignment ──consolidated into──▶ Master consignment
    (client's                    (1..n, one per                (1, groups many houses)
     request)                     client shipment)                      │
                                                                        │ covers
                                                                        ▼
                                                                  Transport leg (1..n)
```

Two directions are in play and they are easy to confuse:

* **Flow** — order *leads to* shipment *leads to* consolidation. This is the creation sequence.
* **Containment **— one master *holds many* houses. The master is the container.

Both are true. "Shipment → consol" is right as a flow and wrong as containment.

## What lives at each level

The workshop draws the line by audience:

> "The house or shipment level contains client-specific information such as shipper, consignee, package counts, volumes, and consignment details. The master level contains carrier-facing information such as airline or shipping-line details, carrier codes, container numbers, and the principal route."

That is exactly how the two classes are populated:

|     | House (`HouseConsignmentRecord`) | Master (`MasterConsignmentRecord`) |
|-----|--------------------------------|----------------------------------|
| Faces | the client                     | the carrier                      |
| Carries | `houseConsignmentReference`, `houseBillNumber`, `headerGoodsDescription`, `headerGrossWeight`, `headerVolume`, `outerPackageCount`, `incoterm`, `shipmentStatusCode` | `masterConsignmentReference`, `consolModeCode`, `carrierBookingReference`, `masterTransportModeCode` |
| Lane | `originLocation` / `destinationLocation` — end-to-end, door to door | `loadPort` / `dischargePort` — port to port |
| Parties | shipper, consignee via role assignment | carrier                          |

The lane distinction matters and is recorded in the model: a house moving Shanghai→Vienna can sit on a consol loading Shanghai and discharging Rotterdam. They are different facts, not different precisions of the same fact.

## Legs

> "A master can also cover multiple transport legs, such as Shanghai-Singapore, Singapore to an intermediate port, and a feeder leg."

`TransportLegRecord` `--legOfMasterConsignment-->` `MasterConsignmentRecord`. The leg is where transport **mode** lives — never on the order, which is mode-agnostic by construction because a door-to-door order is multimodal.

## Order and reservation

The blueprint separates four grains, and the CargoWise booking family maps onto them:

| Grain | Meaning | Canonical class |
|-------|---------|-----------------|
| Order | the client's request to move goods | `booking:TransportOrderRecord` |
| Leg   | one portion of the journey; **mode lives here** | `consignment:TransportLegRecord` |
| Reservation | one carrier's commitment of capacity | `booking:CarrierReservationRecord` |
| Movement | what actually happened | *not yet bound* |

One order may procure many reservations across many modes. That 1..n fan-out is why a transport order is **not** the same thing as a DCSA `Booking` — DCSA's Booking is a single carrier's reservation, which is why `CarrierReservationRecord` is the class that inherits from it.

The order is also distinct from a purchase order:

> "A purchase order represents the client buying products from a supplier… The transport order represents the request for Fracht or another logistics provider to move or coordinate goods. It may contain a purchase-order or sales-order reference, but… [they] are distinct business concepts."

Hub PR #42 extends `booking` from one entity to four, adding `CarrierReservationRecord`, `BookingInstructionRecord` and `BookingConfirmationRecord` under the order.


---

# 2. Parties

## Durable identity, roles in context

This is the single most important structural rule in the party model, and the workshop states it directly:

> "A party is a durable identity that can hold different roles in different orders, shipments, bookings, or itineraries. The role is derived from the relationship between the party and the relevant business entity and should be represented through a role-assignment structure rather than duplicating the party as separate shipper, consignee, carrier, or forwarder subclasses."

So there is exactly one `FrachtPart``y` per organisation, and its roles are separate objects:

```
FrachtParty ◀──assignedToParty── ConsignmentPartyRoleAssignment ──inContextOfConsignment──▶ HouseConsignmentRecord
     ▲                                    (shipper / consignee / notify, on THIS shipment)
     │
     └──assignedParty── PartyRole ──roleFrachtCompany──▶ FrachtLegalEntity
                        (customer / creditor, with THIS Fracht company)
```

The same organisation is a shipper on one shipment and a consignee or carrier on another. There is no `Shipper` class and there should never be one.

Two role structures exist because there are two contexts:

* `**ConsignmentPartyRoleAssignment**` — role *on a shipment* (shipper, consignee, notify).
* `**PartyRole**` — commercial relationship *with a Fracht company* (customer, creditor, debtor account codes).

## Identity and contact

> "Party identifiers must support multiple identifier types, including business registration numbers, VAT or tax numbers, legal entity identifiers, DUNS numbers, and country-specific identifiers. The model should represent the identifier type and value, with country context."

`PartyIdentification` is a type/value pair, not a column per scheme:

```
PartyIdentification ──identifiedParty──▶ FrachtParty
                    ──identificationCodeType──▶ PartyIdentificationCodeType
```

Adding a new identifier scheme means adding a **code-type row**, not an ontology property. This is what lets a second source drop in: Carlo supplies eleven identifier fields (DUNS, GLN, EORI, VAT, SCAC, PEPPOL, port-community IDs) and all eleven become rows.

`PartyContact --contactParty--> FrachtParty` holds people.

## Fracht's own organisation is not a party

Fracht's internal structure is modelled separately, because it is not a counterparty:

```
FrachtStaffMember ──homeBranch──▶ FrachtBranch ──belongsToLegalEntity──▶ FrachtLegalEntity
```

A small number of parties *are* Fracht companies (they hold an org record so they can be invoiced), which is why `FrachtParty --representsLegalEntity--> FrachtLegalEntity` exists and is null for almost every party.


---

# 3. Cargo, equipment and route

**Cargo** hangs off the consignment: `CargoPackageLine` carries package-level detail (`jobpacklines`), specialising `mmt:PackageSpecification`.

**Equipment** attaches to the master, not the house: `FreightContainerRecord --loadedOnMasterConsignment--> MasterConsignmentRecord`. Container TEU therefore sits at consol grain — it cannot be pushed down to a single house without an allocation rule, which is why consolidation ratio is measurable but per-house TEU is not.

**Route and voyage** are the physical maritime layer:

```
PortCallRecord ──partOfVoyage──▶ MaritimeVoyageRecord ◀──onVoyage── TransportCallRecord
      │                                                                    │
      └──atPort──▶ LocationRecord ◀──atLocation─────────────────────────────┘
```

`SailingScheduleRecord` carries planned sailings.


---

# 4. Financial

```
InvoiceLineRecord ──partOfInvoice──▶ InvoiceRecord

ChargeRecord ──chargedToConsignment──▶ HouseConsignmentRecord
             ──hasChargeCode──▶ ChargeCodeRecord
```

`ChargeRecord` is what makes job P&L work: revenue and cost lines attach to the house consignment, so profit is measurable at the grain the client cares about.

The workshop bounds this deliberately — transport cost and customer charge lines that live in the TMS are in scope; centralised accounting integration is not.


---

# 5. Reference data

Everything code-like resolves to a governed list rather than a free-text column:

| Concept | Class | Source |
|---------|-------|--------|
| Location | `LocationRecord --inCountry--> CountryRecord` | UN/LOCODE |
| Port, Airport | `Port`, `Airport` | UN/LOCODE, function-classified |
| Carrier code | `CarrierCodeRecord` ← `FrachtParty --hasCarrierCode-->` | SCAC / IATA |
| Charge code | `ChargeCodeRecord` | `accchargecode` |
| Identifier type | `PartyIdentificationCodeType` | governed seed |
| General codes | `ReferenceCode` | `cuscodedata`, `glbcapability`, `glbdepartment` |

Note `LocationRecord` comes from **UN/LOCODE**, not from CargoWise — the reference layer is source-independent on purpose.


---

# 6. Events

The workshop treats events as a first-class cross-cutting concept:

> "Events should be organized at transport, equipment, and document levels and linked to the relevant object in the shipment hierarchy, such as a house bill, master bill, container, consignment, or transport leg."

with a four-value timing vocabulary — **requested, planned, estimated, actual** — and the rule that duration-bearing activities use start/end while point-in-time events use arrival/departure. That is the same `temporal-quartet` rule the blueprint states normatively.

`events:UnifiedTransportEvent` exists in the ontology, specialising `mmt:TransportEvent`.


---

# 7. Concept mapping table

Every row is an authored binding. "CargoWise" lists the tables actually read; where more than one is listed the model joins them.

## Transport spine

| Concept | CargoWise | Canonical class | Industry model |
|---------|-----------|-----------------|----------------|
| Transport order | `dtbbooking` | `booking:TransportOrderRecord` | `blueprint/transport-order:TransportOrder` |
| Carrier reservation | *(PR #42)* | `booking:CarrierReservationRecord` | `blueprint:CarrierReservation` + `dcsa/booking:Booking` |
| House consignment | `jobshipment` + `jobconshiplink` + `jobheader` | `consignment:HouseConsignmentRecord` | `mmt/consignment:HouseConsignment` |
| Master consignment | `jobconsol` | `consignment:MasterConsignmentRecord` | `mmt/consignment:MasterConsignment` |
| Transport leg | `jobconsoltransport` | `consignment:TransportLegRecord` | `mmt/consignment:TransportLeg` |
| Inland haulage | `jobdocsandcartage` | `intermodal:InlandExecutionInstruction` | `mmt/inland-transport:HaulageInstructions` |

## Party

| Concept | CargoWise | Canonical class | Industry model |
|---------|-----------|-----------------|----------------|
| Party   | `orgheader` + `orgaddress` | `party:FrachtParty` | `bsp/party:TradeParty` |
| Role on a shipment | `jobdocaddress` + `jobshipment` + `jobconsol` | `party:ConsignmentPartyRoleAssignment` | `bsp/party:TradePartyRoleAssignment` |
| Commercial role | `orgcompanydata` | `party:PartyRole` | `bsp/party:TradePartyRoleAssignment` |
| Contact | `orgcontact` | `party:PartyContact` | `bsp/party:Contact` |
| Identifier | `orgcuscode` | `party:PartyIdentification` | `ns/cargo:OtherIdentifier` |
| Fracht legal entity | `glbcompany` | `fracht-company:FrachtLegalEntity` | hub-local      |
| Fracht branch | `glbbranch` | `fracht-company:FrachtBranch` | hub-local      |
| Fracht staff | `glbstaff` | `fracht-company:FrachtStaffMember` | hub-local      |

## Cargo, equipment, route

| Concept | CargoWise | Canonical class | Industry model |
|---------|-----------|-----------------|----------------|
| Package line | `jobpacklines` | `cargo:CargoPackageLine` | `mmt/cargo:PackageSpecification` |
| Container | `jobcontainer` + `refcontainer` | `equipment:FreightContainerRecord` | `dcsa/equipment:Container` |
| Voyage  | `jobvoyage` | `vessel-maritime:MaritimeVoyageRecord` | `imo/port-call:Voyage` |
| Port call | `jobvoydestination` | `vessel-maritime:PortCallRecord` | `imo/port-call:PortCall` |
| Transport call | `jobvoyorigin` | `route-schedule:TransportCallRecord` | `dcsa/transport-call:TransportCall` |
| Sailing schedule | `jobsailing` | `route-schedule:SailingScheduleRecord` | `dcsa/schedule:SailingSchedule` |
| Product | `orgsupplierpart` | `commercial:SupplierPartProduct` | `bsp/commercial:Product` |

## Financial, documents, customs

| Concept | CargoWise | Canonical class | Industry model |
|---------|-----------|-----------------|----------------|
| Charge  | `jobcharge` + `jobheader` | `financial:ChargeRecord` | `bsp/financial:Charge` |
| Invoice | `acctransactionheader` + `jobcominvoiceheader` | `financial:InvoiceRecord` | `bsp/financial:Invoice` |
| Invoice line | `acctransactionlines` + `jobcominvoiceline` | `financial:InvoiceLineRecord` | `bsp/financial:InvoiceLine` |
| Dispute | `accqueryclaim` | `financial:FinancialDisputeRecord` | `dcsa/demurrage-detention:DisputeRecord` |
| Required document | `jobrequireddocument` | `documents:RequiredDocument` | `mmt/documents:TransportDocument` |
| Customs declaration | `jobdeclaration` | `customs:CustomsDeclarationRecord` | `mmt/documents:CustomsDeclaration` |
| Transit declaration | `cusinbondheader` | `customs:TransitDeclarationRecord` | `wco/customs:TransitDeclaration` |
| Declaration goods item | `cusisfline` | `customs:DeclarationGoodsItem` | `wco/customs:GoodsItem` |

## Reference data

| Concept | Source | Canonical class | Industry model |
|---------|--------|-----------------|----------------|
| Location | UN/LOCODE | `reference-data:LocationRecord` | `dcsa/locations:Location` |
| Country | UN/LOCODE | `reference-data:CountryRecord` | `bsp/reference-data:Country` |
| Port / Airport | UN/LOCODE | `reference-data:Port` / `Airport` | `dcsa/locations` |
| Carrier code | `refairline` + `refshippingline` | `reference-data:CarrierCodeRecord` | `ns/cargo:CodeListElement` |
| Charge code | `accchargecode` | `reference-data:ChargeCodeRecord` | `ns/code-lists:ChargeCode` |
| Reference code | `cuscodedata`, `glbcapability`, `glbdepartment` | `reference-data:ReferenceCode` | `ns/cargo:CodeListElement` |
| Identifier type | governed seed | `reference-data:PartyIdentificationCodeType` | `ont/reference-data:ReferenceCode` |

The reference models drawn on: **MMT** (multimodal transport — the consignment spine), **BSP** (business service party/financial), **DCSA** (container shipping), **IMO** (port call and vessel), **WCO** (customs), **IATA ONE Record** (`ns/cargo`, code lists), and the Kairos **blueprint** tier for transport order and carrier reservation.


---

# 8. Relationship reference

Every authored relationship in the hub, as a single list. Read `A --property--> B` as "A holds the foreign key to B" — the many side is always on the left.

```
ConsignmentPartyRoleAssignment --assignedToParty----------▶ FrachtParty
ConsignmentPartyRoleAssignment --inContextOfConsignment---▶ HouseConsignmentRecord
PartyContact                   --contactParty-------------▶ FrachtParty
PartyIdentification            --identifiedParty----------▶ FrachtParty
PartyIdentification            --identificationCodeType---▶ PartyIdentificationCodeType
PartyRole                      --assignedParty------------▶ FrachtParty
PartyRole                      --roleFrachtCompany--------▶ FrachtLegalEntity
FrachtParty                    --representsLegalEntity----▶ FrachtLegalEntity
FrachtParty                    --hasCarrierCode-----------▶ CarrierCodeRecord
FrachtBranch                   --belongsToLegalEntity-----▶ FrachtLegalEntity
FrachtStaffMember              --homeBranch---------------▶ FrachtBranch

HouseConsignmentRecord         --partOfMasterConsignment--▶ MasterConsignmentRecord
HouseConsignmentRecord         --originLocation-----------▶ LocationRecord
HouseConsignmentRecord         --destinationLocation------▶ LocationRecord
HouseConsignmentRecord         --controllingBranch--------▶ FrachtBranch
HouseConsignmentRecord         --salesRepresentative------▶ FrachtStaffMember
HouseConsignmentRecord         --operationsRepresentative-▶ FrachtStaffMember
MasterConsignmentRecord        --loadPort-----------------▶ LocationRecord
MasterConsignmentRecord        --dischargePort------------▶ LocationRecord
TransportLegRecord             --legOfMasterConsignment---▶ MasterConsignmentRecord
FreightContainerRecord         --loadedOnMasterConsignment▶ MasterConsignmentRecord

ChargeRecord                   --chargedToConsignment-----▶ HouseConsignmentRecord
ChargeRecord                   --hasChargeCode------------▶ ChargeCodeRecord
InvoiceLineRecord              --partOfInvoice------------▶ InvoiceRecord

PortCallRecord                 --partOfVoyage-------------▶ MaritimeVoyageRecord
PortCallRecord                 --atPort-------------------▶ LocationRecord
TransportCallRecord            --onVoyage-----------------▶ MaritimeVoyageRecord
TransportCallRecord            --atLocation---------------▶ LocationRecord
LocationRecord                 --inCountry----------------▶ CountryRecord
```

PR #42 adds five more, linking the booking chain and giving the booking domain its first edges into consignment.


---

# Appendix — the workshop's own matching

For traceability, the transcript records this mapping from its conformance analysis:

> "CargoWise concepts such as JobHeader, JobShipment, JobConsol, and JobContainer were matched to industry concepts such as transport order, house consignment, master consolidation, and transport equipment."

`JobShipment`, `JobConsol` and `JobContainer` match what is built. `JobHeader` — the commercial job header carrying job number, direction, transport mode, status and quote reference — currently contributes two staff-code columns to `HouseConsignmentRecord` and is not an entity of its own. Its treatment is open; see the fit/gap document.