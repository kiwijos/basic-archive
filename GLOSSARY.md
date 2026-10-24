# Ship Archive Lite

A proof-of-concept archive where scanned or photographed ship documents are transcribed automatically, corrected by a person, and made searchable by the public.

## Language

**Document**:
One physical archive item (a letter, a blueprint, a photographed object) described by metadata. A Document has one or more Images.
_Avoid_: Record, item, file

**Image**:
One uploaded scan or photograph of a Document, ordered by page number. Every upload creates one Document with one Image.
_Avoid_: Scan, page, photo, master

**Transcription**:
The text read from an Image, either by machine or by a person. Transcriptions are never overwritten: each edit adds a new one.
_Avoid_: OCR result, text

**Machine transcription**:
A Transcription produced automatically by OCR, recording the engine that made it.
_Avoid_: OCR layer, automatic text, draft

**Human transcription**:
A Transcription entered or corrected by a person, recording who made it.
_Avoid_: Verified layer, corrected text, reviewed text

**Current text**:
The text shown for an Image: its latest Human transcription, otherwise its latest Machine transcription.
_Avoid_: Final text, best text

**Verified**:
An Image is verified when it has at least one Human transcription; a Document is verified only when every one of its Images is. Search results always carry this flag, derived from the Transcriptions and never from the Review status. Partly verified Documents still appear in the reviewer queue.
_Avoid_: Approved, confirmed

**Review status**:
Where an Image sits in the staff workflow: pending, ocr_done, verified or failed. It drives the reviewer queue and is separate from Verified.
_Avoid_: Transcription status

**Staff**:
A person allowed to upload and review, identified by a named access token so every Human transcription has a real author.
_Avoid_: User, admin, reviewer

**Rights**:
The licence under which an Image may be reused (CC0, PDM, CC BY or reserved). Metadata is CC0 for every record.
_Avoid_: Licence status, copyright status

### Subjects

**Subject**:
Anything a Document can be about and the archive describes in its own right. Today a Subject is a Ship or an Organisation.
_Avoid_: Entity, record, object

**Ship**:
One continuous life of a vessel. A rename or a sale keeps the same Ship; a hull rebuilt into a new vessel is a new Ship linked to the old one.
_Avoid_: Vessel, boat

**Organisation**:
A company or yard that built, owned or operated a Ship.
_Avoid_: Company, shipyard, owner

**Name**:
A name a Subject carried during a period. A Subject has many Names over its life, and search matches all of them.
_Avoid_: Former name, alias, title

**Relation**:
A dated statement that links one Subject to another, such as built by, owned by or rebuilt from.
_Avoid_: Link, association, ownership record

**Uncertain date**:
A date kept as written (for example "ca 1890") together with the earliest and latest dates it could mean.
_Avoid_: Fuzzy date, approximate date

**External reference**:
A fact about a Subject taken from another source, kept with where it came from, its identifier there and when it was fetched. For now the only source is Wikidata, and a person always chooses the match; nothing is matched automatically.
_Avoid_: Link, enrichment, linked data

**Source key**:
The pair of a source system (such as `seed` or `wikimedia-commons`) and an identifier in it, which a Document, Ship or Organisation may carry to say where it came from. It is unique, cannot be changed, and stays reserved after the record is deleted, which is how loading the demo data twice finds the first copy instead of making a second.
_Avoid_: External id, import id
