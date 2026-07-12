# Legal Intelligence Collection Layer — Instructions

**Έκδοση:** 2.0 (Claude Code build)
**Ημερομηνία:** Ιούλιος 2026
**Πελάτης:** [Client name — χονδρικό εμπόριο καπνικών/τροφίμων + retail food-service]
**Owner (REBORRN):** [PM name]
**Owner (Client):** Νομικό τμήμα — [contact]
**Companion document:** `cowork-agents.md` (agent layer specs)

---

## 1. Σκοπός & αρχιτεκτονικός διαμοιρασμός

Αυτό το αρχείο περιγράφει την αρχιτεκτονική και τις οδηγίες υλοποίησης για ένα σύστημα νομικής/κανονιστικής παρακολούθησης (**horizon scanning + relevance triage + interpretation**), το οποίο θα τροφοδοτεί το compliance work του νομικού τμήματος του πελάτη.

### 1.1 Two-environment architecture

Το σύστημα χωρίζεται σε **δύο runtime environments** που συνεργάζονται μέσω Notion ως shared state:

**Environment A — Claude Code (production infrastructure)** — ΤΟ SCOPE ΑΥΤΟΥ ΤΟΥ DOCUMENT
- Reliable, scheduled, deterministic pipeline
- Contains:
  - Όλα τα source integrations (Tier 1 APIs, Tier 2 scrapers, Tier 3 email intake)
  - Storage & Notion sync
  - Orchestration, scheduling, monitoring, alerting, cost tracking
  - **Production agents** (via Claude Agent SDK) που τρέχουν αυτόματα:
    - Triage Agent (Class A/B/C decision)
    - Interpretation Agent (structured legal analysis για Class A)
    - Quality Observer Agent (weekly retros, drift detection, cost analysis)
- Users: Never touched by legal team directly — runs 24/7 in background

**Environment B — Cowork (legal team's agent toolkit)** — ΣΥΝΟΔΕΥΤΙΚΟ DOCUMENT `cowork-agents.md`
- On-demand, conversational agents που καλεί η νομική ομάδα
- Contains:
  - "Explain Classification" agent (γιατί ταξινομήθηκε έτσι;)
  - "Reclassify" agent (νομίζω ότι αυτό το B πρέπει να είναι A)
  - "Similar Cases" agent (βρες σχετικά items στο database)
  - "Client Communication Draft" agent
  - "Policy Update Draft" agent
  - "Deep Dive" agent (πιο εκτενής ανάλυση από την standard interpretation)
  - "Ontology Refinement Assistant" (chat για ontology changes)
- Users: Legal team invokes ad-hoc

**Communication protocol**: Notion είναι το single source of truth. Claude Code γράφει items με explicit status values. Cowork agents διαβάζουν και μπορούν να γράψουν annotations, drafts, updated fields. State transitions είναι explicit και observable.

### 1.2 State machine (Notion status field)

Το κάθε item περνά από μια σαφή ροή statuses. Το Claude Code διαχειρίζεται τις αυτόματες transitions· Cowork agents και humans μπορούν να επηρεάσουν συγκεκριμένες transitions.

```
[Claude Code] Ingested → New
[Claude Code] Deduped + normalized → Awaiting Triage
[Claude Code Triage Agent] processes → one of:
  ├── Class A - Awaiting Interpretation
  ├── Class B - Indexed (terminal, index-only)
  └── Class C - Awaiting Human Review
[Claude Code Interpretation Agent] processes A items → Class A - Draft Interpretation
[Human reviewer in Notion] → one of:
  ├── Class A - Approved (moves to actions if needed)
  ├── Class A - Rejected (kicks back to Interpretation Agent με feedback)
  └── Class A - Requires Action
[Human, optionally with Cowork agents] → Class A - Archived
[Human on Class C] → Class A - Awaiting Interpretation OR Class B - Indexed
```

### 1.3 Scope ανά φάση υλοποίησης

**Φάση 0 — Scaffolding**: Repo structure, DB/Notion schema, orchestration skeleton, cost ledger, monitoring — με fake data. Validate ότι όλη η ροή δουλεύει conceptually πριν κάνουμε investment σε 10+ source connectors.

**Φάση 1 — Collection layer** (§§ 2-6): Tier 1 APIs first (EUR-Lex, Δι@ύγεια, Βουλή, EDPB, EFSA, GDPRhub), μετά Tier 2 scrapers, μετά Tier 3 email intake.

**Φάση 2 — Triage & Interpretation agents** (§§ 7-9): Οι scheduled agents μέσω Claude Agent SDK. Στην αρχή τρέχουν στα fake items του Phase 0, μετά στα real items από Phase 1.

**Φάση 3 — Human workflows & Notion polish** (§10): Views, review flows, notifications. Παράλληλα, η νομική ομάδα αρχίζει να δοκιμάζει τους Cowork agents (companion doc).

**Φάση 4 — Calibration** με τα 100 pre-labeled items: Threshold tuning, prompt refinement.

**Φάση 5 — Production launch + iterative refinement**.

### 1.4 Domains που καλύπτονται

1. **Πολιτικές & διαδικασίες** (οριζόντιο)
2. **Data Protection / GDPR**
3. **ESG / Sustainability reporting**
4. **Νομοθεσία & compliance τροφίμων**
5. **Franchise / ανταγωνισμός / κάθετες συμφωνίες**
6. **Τομεακά — κυρίως καπνικά (ΕΦΚ, ιχνηλασιμότητα), τελωνειακά, εργατικά, φορολογικά**

### 1.5 Τι θέλουμε από κάθε πηγή

Για κάθε νομικό/κανονιστικό γεγονός (νόμος, ΠΔ, ΥΑ, εγκύκλιος, δικαστική απόφαση, γνωμοδότηση, ανάκληση, διαβούλευση), θέλουμε τα ακόλουθα πεδία:

| Πεδίο | Περιγραφή |
|---|---|
| `source_id` | Μοναδικό ID στην πηγή (πχ CELEX, ΑΔΑ Δι@ύγειας, αρ. απόφασης) |
| `source_name` | Όνομα πηγής (EUR-Lex, ΦΕΚ, EDPB κλπ.) |
| `title` | Τίτλος |
| `type` | Regulation / Directive / Νόμος / ΠΔ / ΥΑ / Εγκύκλιος / Απόφαση / Γνωμοδότηση / Διαβούλευση / Ανάκληση |
| `authority` | Εκδούσα αρχή |
| `date_published` | Ημερομηνία δημοσίευσης |
| `date_effective` | Ημερομηνία έναρξης ισχύος (αν διαφέρει) |
| `url` | Επίσημο URL |
| `full_text` | Full text (plain ή HTML) |
| `topics` | Compliance topics (from ontology — βλ. §4) |
| `jurisdiction` | GR / EU / other |
| `language` | el / en / other |
| `raw_metadata` | Ολόκληρο το raw response από την πηγή (JSON blob) |
| `collected_at` | Timestamp συλλογής |
| `hash` | SHA-256 του full text (για deduplication) |

---

## 2. Αρχιτεκτονική — 3-Tier Model

Οι πηγές χωρίζονται σε τρία tiers βάσει του τύπου integration:

### Tier 1 — Structured APIs (πρώτη προτεραιότητα)

Πηγές με επίσημο REST/SPARQL/RSS. Υψηλή αξιοπιστία, χαμηλό maintenance overhead.

**Πηγές:**
- EUR-Lex / CELLAR (SPARQL + REST + Atom)
- Βουλή των Ελλήνων (REST JSON/XML)
- Δι@ύγεια (REST JSON) — καλύπτει έμμεσα ΕπΑντ, ΑΑΔΕ, ΕΦΕΤ, ΑΠΔΠΧ, όλα τα υπουργεία
- EDPB (2× RSS)
- EFSA (RSS + OpenFoodTox API)
- GDPRhub (MediaWiki API)
- data.gov.gr (REST)

### Tier 2 — Scraping με monitoring

Πηγές χωρίς API. Χρειάζονται browser automation, με fallback και change-detection.

**Πηγές:**
- Εθνικό Τυπογραφείο (search.et.gr) — για ΦΕΚ
- Συμβούλιο της Επικρατείας (adjustice.gr)
- Επιτροπή Ανταγωνισμού (epant.gr) — και μέσω Δι@ύγειας
- ΕΦΕΤ (efet.gr) — ανακλήσεις, δελτία τύπου
- ΑΑΔΕ (aade.gr) — εγκύκλιοι/αποφάσεις σε PDF
- RASFF Window (webgate.ec.europa.eu/rasff-window)
- Αρχή Προστασίας Δεδομένων (dpa.gr) — αποφάσεις

### Tier 3 — Commercial subscriptions (safety net)

Ήδη υπάρχουσες υπηρεσίες που κρατάμε ως human-curated backup layer.

**Πηγές:** dikaio.ai, Qualex, NB Daily, Lawspot, Lawnet, kodiko.gr, taxheaven.gr, forin.gr, newsletters δικηγορικών γραφείων.

**Διαχείριση:** Newsletter forwards σε ένα dedicated email → parser → staging. Παρακολούθηση όχι για comprehensive coverage αλλά για **cross-validation** και για ό,τι δεν πιάνει το Tier 1/2.

---

## 3. Data model & storage staging

### 3.1 Storage architecture — δύο δυνατά paths

Το σύστημα μπορεί να ξεκινήσει σε δύο διαφορετικές διαμορφώσεις. Ξεκάθαρη σύσταση: **Path B (Notion-first)** για MVP, migration σε Path A μόνο αν φτάσουμε πάνω από ~50k items ή αν χρειαστούμε heavy analytics.

**Path A — Full DB backend (originally described)**:

```
[Sources] → [Staging DB] → [Normalized DB] → [Notion sync (Phase 2 UI)]
```

Pros: analytics-friendly, versioning, backup, scales indefinitely.
Cons: extra infrastructure, more moving parts, DevOps overhead.

**Path B — Notion-first (recommended for MVP)**:

```
[Sources] → [Ingestion workers] → [In-memory dedup & normalization] → [Notion (single source of truth)]
                                                                             ↓
                                                                     [Optional export to DB later]
```

Pros: single system, no separate DB to maintain, immediate UX for legal team, faster MVP.
Cons: harder complex queries (Notion API is slower & rate-limited), 50k+ pages start to feel slow, no versioning without extra work.

**Migration path**: Αν αρχίσουμε Path B και χρειαστούμε Path A αργότερα, μπορούμε να export-άρουμε ολόκληρο το Notion σε PostgreSQL μέσω Notion API — retention των IDs κρατά το backlink.

### 3.2 What we capture per event

Για κάθε νομικό/κανονιστικό γεγονός, τα fields όπως ορίστηκαν στο §1. Ένα σημαντικό clarification για **temporary storage** για Class C items (§7): κρατούμε το full text σε staging με **TTL 7 ημερών**. Αν εντός SLA η νομική ομάδα ταξινομήσει το item σε A → full text μεταφέρεται σε permanent. Αν σε B ή αν το SLA λήξει χωρίς decision → purge full text, κρατάμε μόνο τα metadata.

### 3.3 Deduplication policy

Είναι κρίσιμο — έχουμε συχνά την ίδια πληροφορία από 2-3 πηγές (π.χ. ένα ΦΕΚ που εμφανίζεται και στο ΕΤ και στο kodiko.gr και μέσω newsletter, ή μια απόφαση ΕπΑντ που έρχεται από Δι@ύγεια αλλά και από τον ιστότοπο της ΕπΑντ).

**Matching signals** (κάθε ένα δίνει partial score):

| Signal | Weight | Λογική |
|---|---|---|
| Exact `source_id` match | 1.0 | Ίδιο CELEX / ΑΔΑ / αριθμός ΦΕΚ = certain match |
| Text hash (SHA-256 normalized) | 0.95 | Ίδιο κείμενο μετά normalization (whitespace, punctuation) |
| Title similarity (Levenshtein > 0.85) | 0.6 | Παρόμοιοι τίτλοι — υποψία duplicate |
| Same authority + same publication date | 0.5 | Εκδότης + ημερομηνία = ισχυρό context signal |
| Topic + entity overlap (>70%) | 0.3 | Ίδιες entities & topics — πιθανό ίδιο θέμα |

**Aggregate score**:
- **≥ 0.95** → certain duplicate (auto-merge)
- **0.70 - 0.94** → probable duplicate (human confirm στο Class C queue)
- **< 0.70** → treated as distinct

**Merge policy — ποιο source "wins"**:

Καθορίζεται ranked authority hierarchy:

1. **Επίσημη πρωτογενής πηγή** (EUR-Lex, Δι@ύγεια, ΕΤ, Βουλή, EDPB, EFSA, dpa.gr, epant.gr, efet.gr) → highest trust, τα δικά της fields γίνονται primary
2. **Επίσημοι aggregators** (kodiko.gr, ΝΣΚ) → secondary
3. **Commercial aggregators** (Qualex, NB Daily, taxheaven, forin) → tertiary
4. **Newsletter/commentary** (δικηγορικά γραφεία) → context only

**Τι κρατάμε από κάθε πηγή στο merge**:

- **Metadata** (title, date, type, authority, url): από την primary πηγή
- **Full text**: από την primary πηγή. Αν η primary δεν έχει full text (πχ commercial πηγή έχει πιο πλήρες), fall back στην επόμενη
- **Cross-references**: κρατάμε όλα τα source URLs σε array `additional_sources: [{source, url, collected_at}]`
- **Interpretation from commentary**: αν μια commercial πηγή έχει editorial commentary που η επίσημη δεν έχει, το κρατάμε σε ξεχωριστό field `external_commentary` για χρήση κατά το interpretation stage

**Idempotency**: Ο ίδιος `source_id + source_name` καταγράφεται μία φορά. Second time seen → update `last_seen_at` timestamp, όχι νέα record.

**Version handling**: Αν η πηγή δίνει corrigendum / amended version (νέο CELEX suffix, νέα ΑΔΑ), δημιουργείται νέο record με `supersedes` relation προς το προηγούμενο. Interpretation ξανατρέχει.

---

## 4. Compliance topic ontology

**Το ontology είναι input από τη νομική ομάδα του πελάτη — απαιτείται πριν προχωρήσουμε σε production tagging.**

### Δομή

Κάθε topic έχει:

```yaml
topic_id: "vertical_agreements"
name_gr: "Κάθετες συμφωνίες"
name_en: "Vertical agreements"
domain: "competition"
keywords_gr: ["κάθετη συμφωνία", "κάθετος περιορισμός", "δίκτυο διανομής", "franchise", "αποκλειστική διανομή"]
keywords_en: ["vertical agreement", "vertical restraint", "selective distribution", "exclusive distribution"]
celex_types: ["32022R0720"]  # π.χ. Vertical Block Exemption Regulation
eurovoc_descriptors: ["competition law", "distribution agreement"]
authorities: ["EpAnt", "DG COMP", "CJEU"]
priority: "high"  # high/medium/low — για alerting
```

### Αρχική λίστα topics (draft — θα επικυρωθεί από legal team)

**Οριζόντια**
- Εταιρικό δίκαιο & ΓΕΜΗ
- Εργατικό δίκαιο & ΣΕΠΕ
- Φορολογία εισοδήματος & ΦΠΑ
- myDATA / e-invoicing

**Data Protection**
- GDPR — υποχρεώσεις υπευθύνου επεξεργασίας
- GDPR — δικαιώματα υποκειμένου
- Cookies & ePrivacy
- CCTV / βιντεοεπιτήρηση
- Απευθείας εμπορική προώθηση (spam/telemarketing)
- Data breaches & notification
- International data transfers

**ESG**
- CSRD scope & thresholds
- ESRS reporting
- CSDDD (due diligence)
- Taxonomy Regulation
- CBAM (αν αφορά imports)
- EUDR — deforestation regulation (καφές, cocoa κ.λπ.)
- Packaging & PPWR

**Τρόφιμα**
- Food labeling — Reg. 1169/2011
- Health claims — Reg. 1924/2006
- Additives — Reg. 1333/2008
- HACCP & food hygiene
- Allergen management
- Origin labeling
- Food recall procedures

**Franchise / ανταγωνισμός**
- Vertical Block Exemption Regulation (VBER)
- Κάθετες συμφωνίες — κατευθυντήριες γραμμές
- Δεσπόζουσα θέση — άρθρο 102 ΣΛΕΕ
- Συγκεντρώσεις επιχειρήσεων
- State aid (αν αφορά)

**Καπνικά (κρίσιμο)**
- TPD — Tobacco Products Directive
- Ιχνηλασιμότητα καπνικών (ΕΚΜΕΑ)
- ΕΦΚ βιομηχανοποιημένων καπνών
- Ένσημες ταινίες φορολογίας
- Ηλεκτρικά θερμαινόμενα προϊόντα καπνού & e-cigarettes
- Απαγόρευση καπνίσματος — retail επιχειρήσεις

**Retail / food-service specific**
- Καταναλωτής — αθέμιτες πρακτικές
- Franchise agreements
- Αδειοδοτήσεις καταστημάτων υγειονομικού ενδιαφέροντος
- Delivery platforms & gig economy

Αυτή η λίστα πρέπει να επικυρωθεί σε workshop 90' με το νομικό τμήμα, να αποθηκευτεί σε `ontology.yaml` και να αποτελέσει το reference για topic tagging.

---

## 5. Source integration guide

Για κάθε πηγή, τα ακόλουθα:
- **Endpoint(s)**
- **Authentication**
- **Request format**
- **Response schema** (key fields)
- **Polling frequency**
- **Mapping** στο normalized schema μας
- **Known caveats**

---

### 5.1 Tier 1 — Structured APIs

#### 5.1.1 EUR-Lex / CELLAR

**Endpoint SPARQL:** `http://publications.europa.eu/webapi/rdf/sparql`
**Endpoint REST:** `http://publications.europa.eu/resource/celex/{CELEX_ID}` και `http://publications.europa.eu/resource/cellar/{CELLAR_URI}`
**Atom feed για νέα:** `https://eur-lex.europa.eu/EN/display-feed.rss?myRssId=<preferences_id>` (custom feed configurable) + pillar Atom feeds στο CELLAR

**Authentication:** Καμία. Public.

**Rate limits:**
- Query timeout: 60 seconds
- Concurrent connections: < 5 ανά IP — 429/503 → exponential backoff
- Payload: για μεγάλα results (>10k rows) χρειάζεται pagination με `LIMIT/OFFSET`

**Polling frequency:** Atom feed κάθε 30 λεπτά. SPARQL για targeted queries σε on-demand βάση.

**Typical query pattern:**

Για νέα Regulations & Directives τελευταίες 7 ημέρες:

```sparql
PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>

SELECT DISTINCT ?work ?celex ?title ?date ?type
WHERE {
  ?work cdm:resource_legal_id_celex ?celex .
  ?work cdm:work_date_document ?date .
  ?work cdm:work_has_resource-type ?resType .
  ?resType skos:prefLabel ?type .
  ?exp cdm:expression_belongs_to_work ?work .
  ?exp cdm:expression_title ?title .
  ?exp cdm:expression_uses_language ?lang .
  FILTER(?lang = <http://publications.europa.eu/resource/authority/language/ENG>)
  FILTER(?date >= "2026-06-25"^^xsd:date)
  FILTER(?resType IN (
    <http://publications.europa.eu/resource/authority/resource-type/REG>,
    <http://publications.europa.eu/resource/authority/resource-type/DIR>
  ))
}
ORDER BY DESC(?date)
LIMIT 100
```

**Content retrieval:**

```bash
# Metadata (XML notice)
curl -H "Accept: application/xml;notice=object" \
  http://publications.europa.eu/resource/celex/32022R0720

# Full text HTML
curl -H "Accept: text/html" -H "Accept-Language: el" \
  http://publications.europa.eu/resource/celex/32022R0720
```

**Mapping:**

| CELLAR | Normalized |
|---|---|
| CELEX number | `source_id` |
| Cellar URI | `raw_metadata.cellar_uri` |
| ELI | `raw_metadata.eli` |
| Title (per language) | `title` |
| Resource type | `type` |
| `work_date_document` | `date_published` |
| `work_date_entry-into-force` | `date_effective` |
| EuroVoc descriptors | `topics` (via mapping σε ontology) |

**Filtering για compliance domains:**

Χρησιμοποίησε **EuroVoc descriptors** ως προ-φίλτρο. Ενδεικτικά για τον πελάτη:
- `tobacco industry`, `manufactured tobacco`, `excise duty` (καπνικά)
- `foodstuff`, `food safety`, `food labelling`, `food additive` (τρόφιμα)
- `personal data protection` (GDPR)
- `sustainable development`, `corporate social responsibility` (ESG)
- `competition law`, `restrictive-trade practice`, `distribution agreement` (ανταγωνισμός)

**Caveats:**
- Το CELEX ID αλλάζει suffix για corrigenda (π.χ. `32024R1679R(01)`) — treat as separate documents.
- Το SPARQL endpoint κόβει queries χωρίς `LIMIT`.
- Για case-law του CJEU, χρησιμοποίησε τον ίδιο endpoint με `resource-type/JUDG`, `ORDER`, `OPIN_JUR` — αντικαθιστά ουσιαστικά το scraping του InfoCuria.

**Πηγή τεκμηρίωσης:**
- <https://eur-lex.europa.eu/content/help/data-reuse/reuse-contents-eurlex-details.html>
- <https://op.europa.eu/en/web/eu-vocabularies>
- R package `eurlex` (χρήσιμο ακόμα και ως reference implementation)

---

#### 5.1.2 Βουλή των Ελλήνων — Open Data API

**Endpoint:** `https://www.hellenicparliament.gr/api.ashx`

**Authentication:** Καμία.

**Format:** JSON (default) ή XML με `&format=xml`.

**Available methods (via `q` parameter):**

| Method | Περιγραφή |
|---|---|
| `q=Bills` | Νομοσχέδια & τροπολογίες |
| `q=Laws` | Ψηφισθέντες νόμοι |
| `q=Members` | Βουλευτές |
| `q=Themes` | Θεματικές ενότητες |
| `q=Sessions` | Συνεδριάσεις |

(Το πλήρες σετ των methods τεκμηριώνεται στο <https://www.hellenicparliament.gr/opendata/> — verify στο implementation.)

**Example request:**

```bash
curl "https://www.hellenicparliament.gr/api.ashx?q=Bills&period=20"
```

**Polling frequency:** Καθημερινά, γιατί το κοινοβουλευτικό έργο έχει daily rhythm.

**Mapping:**

| API field | Normalized |
|---|---|
| Bill ID | `source_id` |
| Title | `title` |
| Submission date | `date_published` |
| Vote date | `date_effective` (αν ψηφίστηκε) |
| Status | Σε `raw_metadata` |
| Related documents | Σε `raw_metadata.attachments` |

**Χρήση:** Πολύ καλή πηγή για **early warning** — τα βλέπεις πριν καν φτάσουν στη διαβούλευση ή στο ΦΕΚ. Επίσης καλύπτει κοινοβουλευτικές ερωτήσεις που συχνά signal-ουν επικείμενες τροποποιήσεις.

---

#### 5.1.3 Δι@ύγεια (diavgeia.gov.gr)

**Endpoint:** `https://diavgeia.gov.gr/opendata`
**Documentation:** `https://diavgeia.gov.gr/api` (Swagger-style docs)

**Authentication:** Καμία για read-only public data.

**Format:** JSON

**Key endpoints:**

```
GET /opendata/search           # Full-text search πράξεων
GET /opendata/decisions/{ADA}  # Ανάκτηση συγκεκριμένης πράξης
GET /opendata/organizations    # Λίστα φορέων
GET /opendata/types           # Τύποι πράξεων
GET /opendata/subjects        # Θέματα
```

**Example requests:**

```bash
# Πράξεις της Επιτροπής Ανταγωνισμού τις τελευταίες 30 ημέρες
curl "https://diavgeia.gov.gr/opendata/search?q=organizationUid:100026000&from_date=2026-06-01"

# Ανάκτηση συγκεκριμένης πράξης
curl "https://diavgeia.gov.gr/opendata/decisions/ABC123DEF456"
```

**Key organization UIDs (need verification στο implementation):**
- Επιτροπή Ανταγωνισμού
- ΑΑΔΕ
- ΕΦΕΤ
- Αρχή Προστασίας Δεδομένων
- Κάθε αρμόδιο υπουργείο για τον πελάτη (Οικονομικών, Ανάπτυξης, Αγροτικής Ανάπτυξης, Υγείας)

**Polling frequency:** Καθημερινά ή κάθε 6 ώρες για high-priority organizations.

**Mapping:**

| Δι@ύγεια field | Normalized |
|---|---|
| `ada` (ΑΔΑ) | `source_id` |
| `subject` | `title` |
| `decisionType.label` | `type` |
| `organization.label` | `authority` |
| `issueDate` | `date_published` |
| `documentUrl` | `url` (PDF) |
| `documentChecksum` | Για integrity check |

**Χρήση:** **Αυτή είναι ίσως η πιο κρίσιμη πηγή** γιατί καλύπτει έμμεσα ΕπΑντ, ΑΑΔΕ, ΕΦΕΤ, ΑΠΔΠΧ, όλα τα υπουργεία — δηλαδή σχεδόν όλες τις ελληνικές administrative decisions. Πολλά που δεν φτάνουν στο ΦΕΚ (εγκύκλιοι, εσωτερικές αποφάσεις οργάνων) βρίσκονται εδώ.

**Καveat:** Το κείμενο είναι σε PDF — χρειάζεται text extraction pipeline (Tika ή pdfplumber). Για scanned PDFs, OCR.

---

#### 5.1.4 EDPB — European Data Protection Board

**RSS Feeds:**
- News: `https://www.edpb.europa.eu/rss/news_en.rss`
- Publications: `https://www.edpb.europa.eu/rss/documents_en.rss`

**Authentication:** Καμία.

**Format:** RSS 2.0 XML.

**Polling frequency:** Καθημερινά (μικρός όγκος).

**Content:** Guidelines, Opinions (Art. 64), Binding Decisions (Art. 65/66), enforcement statistics. Το πραγματικό content είναι σε PDF — text extraction απαραίτητο.

**Mapping:**

| RSS field | Normalized |
|---|---|
| `<guid>` | `source_id` |
| `<title>` | `title` |
| `<pubDate>` | `date_published` |
| `<link>` | `url` |
| Category tag | `type` (Guidelines/Opinion/Decision) |

**Complementary — GDPRhub decisions coverage:** Για national DPA decisions που δεν εμφανίζονται στα EDPB feeds, χρησιμοποίησε το GDPRhub (§5.1.6).

---

#### 5.1.5 EFSA — European Food Safety Authority

**RSS Feeds:**
- All news: `https://www.efsa.europa.eu/en/rss/all`
- Consultations: `https://www.efsa.europa.eu/en/rss/consultations`
- Scientific outputs: `https://www.efsa.europa.eu/en/rss/scientific-outputs`

**Authentication:** Καμία.

**Format:** RSS 2.0.

**OpenFoodTox API:** Για dose-response και safety assessments — verify current endpoint στο <https://www.efsa.europa.eu/en/microstrategy/openfoodtox>.

**Polling frequency:** Καθημερινά.

**Χρήση:** Καλύπτει scientific opinions & recommendations, όχι enforcement. Το enforcement είναι στο RASFF (§5.2.5) και ΕΦΕΤ (§5.2.4). Χρήσιμο κυρίως για forward-looking view (τι επιστημονικές γνωμοδοτήσεις έρχονται → τι regulatory changes θα ακολουθήσουν).

---

#### 5.1.6 GDPRhub

**Endpoint:** MediaWiki API — `https://gdprhub.eu/api.php`

**Authentication:** Καμία για read.

**Format:** JSON/XML.

**Example — αναζήτηση αποφάσεων:**

```bash
# Λίστα σελίδων στο "Decisions" namespace
curl "https://gdprhub.eu/api.php?action=query&list=allpages&apnamespace=0&format=json&aplimit=50"

# Ανάκτηση περιεχομένου συγκεκριμένης σελίδας
curl "https://gdprhub.eu/api.php?action=parse&page=HDPA_(Greece)_-_45/2024&format=json&prop=wikitext"

# Recent changes για monitoring νέων αποφάσεων
curl "https://gdprhub.eu/api.php?action=query&list=recentchanges&rcnamespace=0&rclimit=50&format=json"
```

**Polling frequency:** Καθημερινά (recentchanges endpoint).

**Χρήση:** Παρέχει **αγγλικές περιλήψεις** αποφάσεων DPAs από όλη την Ευρώπη, με cross-referencing σε GDPR άρθρα. Ιδανικό για comparative analysis. Για ελληνικές αποφάσεις, complements dpa.gr (που δίνει το πρωτότυπο).

**Mapping:**

| MediaWiki field | Normalized |
|---|---|
| Page title | `source_id` + `title` |
| Wikitext parsed | `full_text` |
| Categories | `topics` (χρειάζεται mapping σε ontology) |
| Revision timestamp | `collected_at` |

---

#### 5.1.7 data.gov.gr

**Endpoint:** `https://data.gov.gr/api/v1/`

**Authentication:** Απαιτείται API key (δωρεάν με εγγραφή).

**Format:** JSON, RESTful, GET/POST.

**Χρήση:** Δευτερεύουσα πηγή — datasets από δημόσιους φορείς (economics, health, environment κ.λπ.). Σχετική κυρίως για ESG data enrichment και για compliance context (πχ στατιστικά ελέγχων).

---

### 5.2 Tier 2 — Scraping

**Αρχή:** Χρησιμοποιούμε browser automation (Playwright preferred για JS-heavy sites, requests+BeautifulSoup για static HTML). Κάθε scraper έχει:
- Change detection (checksum HTML section που περιέχει το listing)
- Retry logic με exponential backoff
- User-Agent identifying REBORRN για politeness
- Robots.txt respect
- Rate limiting (max 1 req/2sec per domain)

**Alerting:** Όταν ο scraper σπάει (selector not found, layout change), αυτόματο alert στο ops channel.

---

#### 5.2.1 Εθνικό Τυπογραφείο — ΦΕΚ

**URL:** `https://search.et.gr/en/`

**Approach:**
- Καθημερινό scrape της "Simple Search" με filter `Date Range` = τελευταίες 24h
- Extract PDF URLs για κάθε νέο ΦΕΚ
- Download PDFs → text extraction (Tika/pdfplumber)
- Parse header για να εξάγεις: αριθμό ΦΕΚ, τεύχος, ημερομηνία, τίτλους δημοσιευμάτων

**Playwright script skeleton:**

```python
from playwright.sync_api import sync_playwright

def scrape_fek_daily():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent="REBORRN-LegalIntel/1.0")
        page.goto("https://search.et.gr/en/simple-search/")
        # Set date range filter
        page.fill('input[name="dateFrom"]', get_yesterday())
        page.fill('input[name="dateTo"]', get_today())
        page.click('button:has-text("Search")')
        page.wait_for_selector('.result-item')
        results = page.locator('.result-item').all()
        for r in results:
            yield {
                'fek_number': r.locator('.fek-number').inner_text(),
                'issue': r.locator('.issue').inner_text(),
                'date': r.locator('.date').inner_text(),
                'pdf_url': r.locator('a.pdf-link').get_attribute('href'),
                'title': r.locator('.title').inner_text(),
            }
        browser.close()
```

**Verification στο implementation:** Το ακριβές CSS/XPath selectors πρέπει να επικυρωθούν με τον live site — μπορεί να αλλάξουν, ειδικά μετά τον προγραμματισμένο εκσυγχρονισμό του Εθνικού Τυπογραφείου.

**Polling frequency:** 2× ημέρα (ΦΕΚ βγαίνουν κατά ριπάς).

**Fallback:** kodiko.gr και taxheaven.gr έχουν καλή coverage ΦΕΚ ως cross-check.

---

#### 5.2.2 Συμβούλιο της Επικρατείας (ΣτΕ)

**URLs:**
- `https://www.adjustice.gr/webcenter/portal/ste/ypiresies/nomologies` (search UI)
- `https://www.gov.gr/ipiresies/dikaiosune/dikasteria/anazetese-nomologias` (unified search νομολογίας)

**Approach:**
- Καθημερινό scrape της "Αναζήτηση Νομολογίας"
- Filter: Date range = τελευταία εβδομάδα, Type = ΣτΕ
- Extract decision text (usually .txt ή .doc)
- Parse για: αριθμό απόφασης, τμήμα, ημερομηνία, θεματικές λέξεις-κλειδιά

**Caveat:** Ο site είναι JavaScript-heavy και οι αποφάσεις είναι ανωνυμοποιημένες. Θα χρειαστείς Playwright.

**Complementary source:** Deep Law (deep-law.io) έχει καλύτερη UX για ΣτΕ αν το budget το επιτρέπει — δεν φαίνεται να έχει public API αλλά αξίζει να ρωτηθεί ο vendor για data export.

**Polling frequency:** Καθημερινά.

---

#### 5.2.3 Επιτροπή Ανταγωνισμού (ΕπΑντ)

**URLs:**
- `https://www.epant.gr/apofaseis-gnomodotiseis.html` (αποφάσεις)
- `https://diavgeia.gov.gr/f/epant` (μέσω Δι@ύγειας — προτιμώμενη διαδρομή)

**Approach:**
- **Πρωτεύον:** Χρησιμοποίησε το Δι@ύγεια API (§5.1.3) με filter την ΕπΑντ ως authority. Δεν χρειάζεται scraping.
- **Δευτερεύον:** Scrape του `apofaseis-gnomodotiseis.html` για coverage αποφάσεων που για κάποιο λόγο δεν έχουν αναρτηθεί στη Δι@ύγεια (σπάνιο, αλλά cross-check αξίζει).

**Polling frequency:** Καθημερινά μέσω Δι@ύγειας, εβδομαδιαία το direct scrape.

---

#### 5.2.4 ΕΦΕΤ — Ανακλήσεις & Δελτία Τύπου

**URLs:**
- `https://www.efet.gr/index.php/el/enimerosi/deltia-typou/anakleiseis-cat` (ανακλήσεις)
- `https://www.efet.gr/index.php/el/enimerosi/deltia-typou/anakoinoseis-cat` (ανακοινώσεις)

**Approach:**
- HTML scrape λίστας — extract title, date, snippet, URL για κάθε ανάκληση
- Follow-through στο detail page για full text
- **Critical:** Πάρσε τον τίτλο για να εξάγεις προϊόν & αίτια ανάκλησης (Listeria, υδράργυρος, αλλεργιογόνο κ.λπ.)

**Polling frequency:** Κάθε 4 ώρες — ανακλήσεις τροφίμων είναι time-sensitive.

**Complementary:** RASFF Window (§5.2.5) για ευρωπαϊκή coverage.

---

#### 5.2.5 RASFF Window

**URL:** `https://webgate.ec.europa.eu/rasff-window/screen/list`

**Approach:**
- **Option A (recommended):** Χρήση 3rd party API — Apitalks (api.store) προσφέρει RASFF feed μέσω REST. Vendor lock-in, αλλά χαμηλό effort.
- **Option B:** Playwright scraping του RASFF Window. Ο site είναι Angular-based, θέλει JS rendering.
- **Option C:** Παρακολούθηση EFSA news feed — έμμεση, αλλά δωρεάν και επίσημη.

**Filtering:** Origin country, product category, hazard type. Για τον πελάτη, high-priority: `food`, `feed`, `food contact materials`, hazard `pathogenic microorganisms`, `heavy metals`, `mycotoxins`, `allergens`.

**Polling frequency:** Κάθε 4 ώρες.

---

#### 5.2.6 Αρχή Προστασίας Δεδομένων (dpa.gr)

**URLs:**
- `https://www.dpa.gr/el/enimerwtiko/prakseisArxis` (πράξεις)
- `https://www.dpa.gr/el/enimerwtiko/e-newsletter` (newsletter)

**Approach:**
- **Πρωτεύον:** Subscribe στο e-Newsletter με dedicated email → parser που εξάγει links → HTML fetch για κάθε πράξη
- **Δευτερεύον:** Δι@ύγεια API με ΑΠΔΠΧ ως authority
- **Fallback:** HTML scraping της σελίδας πράξεων

**Content:** Οι αποφάσεις είναι σε HTML pages, όχι PDF — απλό parsing.

**Polling frequency:** Εβδομαδιαία (newsletter cycle) + καθημερινή Δι@ύγεια check.

---

### 5.3 Tier 3 — Commercial subscriptions

Δεν αυτοματοποιούνται πλήρως — αλλά ενσωματώνονται στο pipeline. **Σημαντικό**: το intake δεν χρησιμοποιεί το personal email της νομικής συμβούλου. Τρεις εναλλακτικές, ranked by preference:

**Option 1 — Dedicated shared inbox** (recommended):
- Δημιουργείται mailbox `legal-intel@[client-domain]` που πηγαίνει σε ένα IMAP/API accessible λογαριασμό
- Η νομική σύμβουλος συνεχίζει να λαμβάνει τα newsletters στο δικό της account, αλλά έχει auto-forward rule που **αντιγράφει** (BCC) στο shared inbox — δεν αγγίζει την τρέχουσα ροή της
- Ο parser κοιτάει μόνο το shared inbox, ποτέ το personal

**Option 2 — Browser extension "Send to legal-intel"**:
- Αν η νομική σύμβουλος διαβάζει τα newsletters στο browser, ένα simple bookmarklet ή extension που στέλνει το URL/HTML content στο system
- Πλεονέκτημα: manual curation — μόνο ό,τι θεωρεί χρήσιμο περνάει
- Μειονέκτημα: extra step, εξαρτώμενο από ανθρώπινη πράξη

**Option 3 — Newsletter re-subscription στο shared inbox**:
- Ενεργοποιούνται νέες subscriptions στα Qualex, NB Daily, dikaio.ai κ.λπ. απευθείας στο `legal-intel@` — παράλληλα, χωρίς αλλαγή στο υπάρχον δικό της setup
- Πλεονέκτημα: zero effort από τη νομική σύμβουλο
- Μειονέκτημα: πρόσθετο κόστος αν οι subscriptions είναι per-seat

**Processing του shared inbox**:
- **Email parser** (Zapier / n8n / custom Python IMAP script) που:
  - Extracts links από κάθε newsletter
  - Fetches το content
  - Marks το item ως "commercial source" στο staging (ή Notion)
- **Χρήση:** Ως **cross-validation** για ό,τι πιάνει το Tier 1/2, και ως **safety net** για ό,τι δεν πιάνει (πχ commentary, human editorial).

Το νομικό τμήμα διατηρεί την prerogative να **manual add** entries από αυτές τις πηγές αν κρίνει ότι κάτι είναι σημαντικό και δεν έχει πιαστεί αλλού.

---

## 6. Processing pipeline

```
┌──────────────┐
│ Sources      │  Tier 1: APIs polled by scheduler
│              │  Tier 2: Scrapers (Playwright + requests)
│              │  Tier 3: Email inbox parser
└──────┬───────┘
       │
       ▼
┌──────────────────────┐
│ Ingestion Workers    │  Async workers per source
│ (Python/Node)        │  Emit raw JSON to queue
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐
│ Staging DB           │  PostgreSQL — raw_events table
│                      │  {source_name, raw_payload, collected_at, id}
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐
│ Normalization        │  Per-source mappers → unified schema
│                      │  Text extraction (Tika/pdfplumber)
│                      │  Language detection
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐
│ Deduplication        │  SHA-256 hash on normalized text
│                      │  + source_id + source_name check
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐
│ Topic Tagging        │  Rule-based (keywords from ontology)
│                      │  + LLM classifier for edge cases
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐
│ Relevance Triage     │  Rule-based + LLM classifier
│ (§7)                 │  → Class A / B / C
└──────┬───────────────┘
       │
       ├── Class B (index-only) ────────────────┐
       │                                        │
       ├── Class C (ambiguous) → Human Review ──┤
       │                        Queue (§9 WF1)  │
       │                            │           │
       │                            ▼           │
       │                     Reclassify A or B  │
       │                            │           │
       ▼ Class A                    │           │
┌──────────────────────┐            │           │
│ Interpretation       │            │           │
│ Engine (§8)          │◄───────────┘           │
│ LLM legal analysis   │                        │
└──────┬───────────────┘                        │
       │                                        │
       ▼                                        │
┌──────────────────────┐                        │
│ Human Review         │                        │
│ of Interpretation    │                        │
│ (§9 WF2)             │                        │
│ Draft → Approved     │                        │
└──────┬───────────────┘                        │
       │                                        │
       ▼                                        ▼
┌────────────────────────────────────────────────┐
│ Normalized DB                                   │
│ Class A: full record + interpretation           │
│ Class B: index-only (metadata + URL, no text)   │
│ Class C: transient — resolved to A or B         │
└──────┬─────────────────────────────────────────┘
       │
       ▼
┌──────────────────────┐
│ Notion sync (§10)    │  Class-aware payloads
│                      │  Full page for A, minimal for B
└──────────────────────┘
```

### Scheduling

**Cron-based orchestration (recommended: Prefect, Airflow, ή n8n για non-dev friendliness):**

| Source | Frequency |
|---|---|
| EUR-Lex CELLAR (Atom) | 30 min |
| Δι@ύγεια | 6 hours |
| Βουλή | Daily 08:00 |
| EDPB RSS | Daily 09:00 |
| EFSA RSS | Daily 09:00 |
| GDPRhub | Daily 10:00 |
| ΦΕΚ scrape | 2× daily (10:00, 18:00) |
| ΕΦΕΤ ανακλήσεις | Every 4 hours |
| RASFF | Every 4 hours |
| ΣτΕ | Daily 22:00 |
| ΕπΑντ | Daily via Δι@ύγεια |
| dpa.gr | Weekly + newsletter |
| Commercial emails | Real-time (inbox trigger) |

---

## 7. Relevance triage & content classification

**Υλοποίηση**: Ο Triage Agent τρέχει μέσω **Claude Agent SDK** στο Claude Code environment. Είναι scheduled/event-driven agent — τρέχει όταν item έχει status `Awaiting Triage`. Παράλληλα, στο Cowork υπάρχει **"Explain Classification" agent** που επιτρέπει στη νομική ομάδα να ρωτήσει "γιατί αυτό ταξινομήθηκε έτσι;" για συγκεκριμένα items — βλ. `cowork-agents.md`.

**Οδηγητική αρχή:** Το σύστημα δεν έχει νόημα να αποθηκεύει full text για κάθε δημοσίευμα που περνά από το horizon scanning. Το πραγματικό value είναι να **διακρίνει** τι μας αφορά, να παράγει interpretation μόνο για ό,τι μας αφορά, και να κρατά **index-only records** για ό,τι δεν μας αφορά — ώστε αν κάτι αλλάξει αργότερα (αλλαγή business scope, retroactive relevance), να μπορούμε να το ανακτήσουμε από την πηγή.

### 7.1 Content Classes

| Class | Ορισμός | Τι κρατάμε |
|---|---|---|
| **A — Relevant** | Αφορά τον πελάτη με βεβαιότητα | Metadata + full text + interpretation + client impact + actions |
| **B — Index only** | Δεν αφορά τον πελάτη | Metadata + URL μόνο (χωρίς full text) |
| **C — Ambiguous** | Δεν μπορεί να κριθεί αυτόματα | Metadata + full text (temporary hold) + human review queue |

Ενδεικτικά distributions (για typical horizon scanning ~500-1000 items/μήνα): αναμένουμε 60-70% Class B, 20-25% Class A, 10-15% Class C. Αυτά validate-άρονται και recalibrate-άρονται μετά τους πρώτους 2-3 μήνες.

### 7.2 Ροή αποφάσεων

```
Post topic-tagging →
  ├─ Rule-based signals (deterministic) →
  │    ├─ Explicit include rule matches → Class A (skip LLM)
  │    ├─ Explicit exclude rule matches → Class B (skip LLM)
  │    └─ No decisive rule → pass to LLM classifier
  │
  └─ LLM classifier →
       ├─ relevance=high, confidence > 0.85 → Class A
       ├─ relevance=low, confidence > 0.85 → Class B
       └─ Everything else (medium, or low-confidence) → Class C (human queue)
```

### 7.3 Rule-based signals

Οι κανόνες βρίσκονται στο `relevance_rules.yaml` — separate από το `ontology.yaml` γιατί αλλάζουν πιο συχνά.

**Explicit include rules** (auto Class A):

```yaml
- rule_id: "high_priority_topic_hit"
  when:
    topics_contains_any: ["tobacco_traceability", "ekmea", "food_labeling", 
                          "food_recall", "vertical_agreements", "gdpr_direct_marketing"]
  action: classify_A

- rule_id: "authority_and_sector"
  when:
    authority_in: ["EpAnt", "EFET", "DPA"]
    sector_keywords_any: ["καπνικά", "τρόφιμα", "franchise", "λιανικό εμπόριο"]
  action: classify_A

- rule_id: "kad_direct_mention"
  when:
    text_contains_kad_any: ["46.35", "46.37", "46.38", "56.10", "56.30"]
  action: classify_A
```

**Explicit exclude rules** (auto Class B):

```yaml
- rule_id: "unrelated_sectors"
  when:
    topics_all_in: ["forestry", "military", "religious_affairs", 
                    "urban_planning_non_retail", "maritime"]
  action: classify_B

- rule_id: "personnel_appointments"
  when:
    type_in: ["Διορισμός", "Απόσπαση", "Παραίτηση"]
    subject_not_contains: ["επιτροπή ανταγωνισμού", "εφετ", "αρχή προστασίας"]
  action: classify_B

- rule_id: "boilerplate_procedural"
  when:
    type: "Τροποποίηση"
    text_length_less_than: 500
    no_topic_match: true
  action: classify_B
```

**Sector match & KAD codes** (relevant για τον συγκεκριμένο πελάτη):

- **46.35** — Χονδρικό εμπόριο προϊόντων καπνού
- **46.37** — Χονδρικό εμπόριο καφέ, τσαγιού, κακάο, μπαχαρικών
- **46.38** — Χονδρικό εμπόριο άλλων τροφίμων
- **56.10** — Δραστηριότητες εστιατορίων και ταχυφαγείων
- **56.30** — Δραστηριότητες παροχής ποτών

Άμεση αναφορά KAD στο κείμενο νόμου = strong signal για Class A.

### 7.4 LLM classifier

Χρησιμοποιείται όταν τα rules δεν καταλήγουν σε A ή B.

**Prompt skeleton** (validate με τη νομική ομάδα πριν production):

```
System: You are a legal relevance classifier for a specific business context.

CLIENT PROFILE:
- Sector: Wholesale trade primarily in tobacco products and food
- Secondary: Retail food-service (fast food, HORECA) through franchise
- Jurisdiction: Greece + EU applicable
- KAD codes: 46.35, 46.37, 46.38, 56.10, 56.30

TASK: Given a legal item's metadata and snippet, classify its relevance.

Item:
- Title: {title}
- Type: {type}
- Authority: {authority}
- Jurisdiction: {jurisdiction}
- Date published: {date_published}
- Tagged topics: {topics}
- First 500 chars: {snippet}

Return JSON:
{
  "relevance": "high" | "medium" | "low",
  "confidence": 0.0-1.0,
  "reasoning": "2-3 sentence explanation, in Greek",
  "sector_touchpoints": ["tobacco" | "food_wholesale" | "food_retail" | "franchise" | "cross_functional" | "none"],
  "action_signal": "immediate" | "monitor" | "none",
  "specialist_needed": true | false
}

Guidance:
- HIGH: item creates new obligations, changes existing ones, or exposes 
  client to material risk in its core sectors
- MEDIUM: item is potentially applicable, or affects the sector broadly 
  without clear client impact — flag for human review
- LOW: item does not apply to client operations
- Prefer MEDIUM over guessing HIGH/LOW when uncertain
```

**Recommended model**: Claude Sonnet για efficiency, με option fallback σε Opus για high-stakes topics (πχ CSRD scope changes, ΕπΑντ decisions).

### 7.5 Handling Class B (index-only) — critical design decision

Για Class B items κρατάμε **μόνο** τα εξής:

- `source_id`, `source_name`, `title`, `type`, `authority`
- `date_published`, `date_effective`
- `topics` (as tagged)
- `url` (link πίσω στην πηγή)
- `content_class = B`
- `class_reasoning` (γιατί κρίθηκε Class B)
- `confidence_score`
- `collected_at`

**Δεν** κρατάμε:
- Full text
- Snippet (πέραν του title)
- Raw payload (μετά την ταξινόμηση, μπορούμε να purge το staging record για Class B)

**Reclassification path**: Αν αργότερα η νομική ομάδα κρίνει ότι ένα Class B item έπρεπε να είναι Class A (πχ αλλαγή business scope, νέο business unit που το κάνει relevant), το σύστημα υποστηρίζει `Reclassify to A` action στο Notion, το οποίο τρέχει:
1. Re-fetch από την αρχική πηγή (χρησιμοποιώντας το url)
2. Full text extraction
3. Interpretation engine
4. Human review

Track: rate reclassification B→A. Αν ξεπερνάει το 5% ετησίως, ενδείξη ότι τα rules ή το classifier είναι πολύ αυστηρά — recalibrate.

**Storage benefit**: Ενδεικτικά, ένα Class B record είναι ~500 bytes vs ένα Class A ~50-500KB. Για 700 Class B items/μήνα, σώζουμε ~35GB/έτος storage + το αντίστοιχο interpretation cost (~$0.05-0.10 per Class A item σε LLM API costs). Πιο σημαντικό: μειώνουμε το noise που βλέπει η νομική ομάδα στο Notion κατά 60-70%.

### 7.6 Handling Class C (ambiguous) — temporary storage

Η Class C **δεν αποτελεί μακροπρόθεσμο state**. Είναι transient holding pattern μέχρι ο άνθρωπος αποφασίσει.

**Storage strategy**:
- Full text κρατείται σε **staging** (όχι permanent normalized DB) με **TTL 7 ημερών**
- Metadata (τίτλος, source, date, url, topics, class=C, reasoning) φαίνονται στο Notion queue για review
- Αν εντός SLA (2 εργάσιμες) ο νομικός ταξινομήσει → A → full text promotes σε permanent
- Αν → B → full text purged, μετατροπή σε index-only record
- Αν το TTL λήξει χωρίς decision → alert (probably indicates SLA breach), το item παραμένει στη queue μέχρι decision αλλά με flag `overdue`

**Rationale**: Δεν έχει νόημα να κρατάμε μακροπρόθεσμα το full text ενός item που τελικά ο άνθρωπος έκρινε ως irrelevant. Το TTL είναι διαφανές — αν κάτι δεν κρίθηκε εντός 2 εβδομάδων, κάτι δεν πάει καλά με τη διαδικασία (πιθανά reviewer capacity issue).

---

## 8. Interpretation engine

**Υλοποίηση**: Ο Interpretation Agent τρέχει μέσω **Claude Agent SDK** στο Claude Code environment. Ενεργοποιείται όταν item έχει status `Class A - Awaiting Interpretation`. Παράλληλα, στο Cowork υπάρχουν agents που η νομική ομάδα καλεί ad-hoc για βαθύτερη ανάλυση: **"Deep Dive" agent** (πιο εκτενής ανάλυση από τη standard interpretation), **"Similar Cases" agent** (retrieval σχετικών items), **"Client Communication Draft" agent** — βλ. `cowork-agents.md`.

**Purpose**: Για κάθε Class A item, το σύστημα παράγει μια δομημένη νομική ερμηνεία που εξηγεί τι σημαίνει η αλλαγή για τον πελάτη.

### 8.1 Ορισμός scope

**Τι είναι το interpretation output**:
- First-pass νομική ανάλυση με consistent structured fields
- Reviewable draft για τον νομικό της ομάδας
- Reference material για μελλοντικά cases (few-shot examples)
- Actionable — δείχνει σε τι πρέπει να προβεί ο πελάτης

**Τι ΔΕΝ είναι**:
- Definitive νομική συμβουλή
- Αντικατάσταση της κρίσης του δικηγόρου
- Απλό summary του κειμένου
- Νομικά δεσμευτικό

Κάθε Class A page στο Notion φέρει disclaimer: *"Η ερμηνεία παράγεται αυτόματα και υπόκειται σε νομική επικύρωση. Δεν αποτελεί νομική συμβουλή."*

### 8.2 Structured output schema

```json
{
  "summary": "1-παράγραφος plain-language summary στα ελληνικά",
  "what_changed": {
    "before": "Νομικό/κανονιστικό status quo πριν",
    "after": "Νομικό/κανονιστικό status quo μετά",
    "delta": "Ουσιαστικές διαφορές — bullet form"
  },
  "who_affected": {
    "primary_business_lines": ["tobacco_wholesale", "food_wholesale"],
    "secondary_business_lines": ["food_service_retail", "franchise_network"],
    "support_functions_affected": ["legal", "compliance", "hr", "it", "operations"],
    "excluded_business_lines": []
  },
  "client_impact": {
    "operational": "Impact σε καθημερινές λειτουργίες",
    "financial_qualitative": "Ποιοτική εκτίμηση οικονομικού impact",
    "compliance_new_obligations": [
      "Concrete obligation 1",
      "Concrete obligation 2"
    ],
    "compliance_lifted_obligations": []
  },
  "actions_required": [
    {
      "action": "Συγκεκριμένη ενέργεια",
      "owner_role": "π.χ. DPO / Head of Compliance / Legal Counsel / IT / HR",
      "deadline": "YYYY-MM-DD ή 'ongoing' ή 'upon_next_review'",
      "priority": "high|medium|low",
      "estimated_effort": "low|medium|high"
    }
  ],
  "critical_dates": {
    "publication": "YYYY-MM-DD",
    "entry_into_force": "YYYY-MM-DD",
    "transition_period_end": "YYYY-MM-DD",
    "reporting_deadlines": [
      {"deadline": "YYYY-MM-DD", "description": "..."}
    ]
  },
  "cited_articles": [
    {"article_ref": "Άρθρο 5 παρ. 2", "excerpt": "Verbatim text του άρθρου (max 100 words)"}
  ],
  "related_precedents": [
    {"source_id": "celex_or_ada", "relation": "supersedes|amends|clarifies|contradicts"}
  ],
  "confidence_notes": "Πού είναι αβέβαιη η ανάλυση — π.χ. 'Η έννοια του X δεν έχει ακόμη κριθεί από τα δικαστήρια'",
  "requires_specialist_review": true,
  "specialist_domain": "gdpr|competition|tax|food_safety|labor|other|null"
}
```

### 8.3 Prompt engineering approach

Η ερμηνεία τρέχει σε ένα pipeline βημάτων, όχι σε ένα single mega-prompt:

**Βήμα 1 — Legal type identification**: Τι είδους πράξη είναι; (Νομοθέτημα / Εκτελεστική πράξη / Δικαστική / Ερμηνευτική / Ανάκληση κ.λπ.)

**Βήμα 2 — Scope determination**: Ποιον/ποιους αφορά; Κριτήρια εφαρμογής.

**Βήμα 3 — Delta analysis**: Τι αλλάζει σε σχέση με το προηγούμενο καθεστώς;

**Βήμα 4 — Retrieval augmentation**: Ανακτώνται από το DB related items (same topic tag + same authority + last 3 years) για context.

**Βήμα 5 — Client-specific impact**: Δεδομένου του client profile (από §7.4 CLIENT PROFILE), τι σημαίνει;

**Βήμα 6 — Action extraction**: Concrete actions με owners & deadlines.

**Βήμα 7 — Confidence self-assessment**: Πού είναι αβέβαιη η ανάλυση; Χρειάζεται specialist review;

Κάθε βήμα είναι distinct LLM call ή structured section με chain-of-thought. Ο λόγος είναι δύο: (α) καλύτερη quality per section, (β) traceability όταν κάτι πάει στραβά (ξέρουμε ποιο βήμα).

### 8.4 Few-shot & retrieval

Το prompt περιλαμβάνει:

- **2-3 approved interpretations** από προηγούμενα cases με similar topic tag (few-shot examples). Αυτά αποθηκεύονται σε ξεχωριστό `interpretation_examples` table και curated από τη νομική ομάδα.
- **Retrieval-augmented context**: 3-5 σχετικές προηγούμενες αποφάσεις (same topic + last 3 years) ως background για precedent-aware analysis.
- **Ontology context**: Το topic definition και οι sector touchpoints σχετικά με το client profile.

### 8.5 LLM selection

- **Primary**: Claude Sonnet — για efficient large-volume processing
- **Escalation**: Claude Opus — για CSRD scope items, ΕπΑντ decisions, ΣτΕ αποφάσεις, ή όταν το Sonnet σηκώνει `requires_specialist_review = true`
- **Fallback**: OpenAI GPT-4-class για availability
- **Local option** (αν copyright/confidentiality γίνει concern): fine-tuned Llama ή Mistral στην ίδια dataset

Config σε `interpretation_config.yaml`:

```yaml
default_model: claude-sonnet-4-6
escalation_model: claude-opus-4-7
escalation_triggers:
  - topic_in: ["csrd_scope", "epant_decision", "ste_decision"]
  - self_flag: requires_specialist_review
temperature: 0.2  # low για consistency
max_tokens: 4000
```

### 8.6 Draft state & versioning

Κάθε interpretation ξεκινά ως `Draft`. Δεν είναι visible στην main "Approved" view του Notion μέχρι να περάσει human review.

**Versioning**: Αν το item τροποποιείται (νέα version από την πηγή, ή corrigendum), τρέχει νέο interpretation cycle. Οι προηγούμενες versions κρατούνται με timestamp.

### 8.7 Cold start — απουσία υπάρχοντος knowledge base

Ο πελάτης δεν διαθέτει σήμερα δομημένο knowledge base για να τροφοδοτήσει το interpretation engine. Για να μη ξεκινήσουμε τυφλά, προτείνουμε δύο ξεχωριστά inputs που καλύπτουν το gap:

**Input 1 — Client Context Document (initial curation, ~2 σελίδες)**

Ένα δομημένο κείμενο που η νομική ομάδα φτιάχνει μία φορά και συντηρεί quarterly. Περιλαμβάνει:

- **Business overview**: Τι κάνει η εταιρεία (χονδρικό, λιανικό, franchise), σε τι μεγέθη
- **Business lines & operations**: Concrete list με KAD codes, βασικές δραστηριότητες ανά line
- **Legal entities**: Θυγατρικές, joint ventures, franchise structure
- **Historical compliance sensitivities**: Ιστορικά έχουν εμφανιστεί issues σε (πχ) labeling, tobacco excise, GDPR direct marketing — το LLM αυτά τα ξέρει σαν areas of higher scrutiny
- **Current known obligations**: Ενεργά licenses, active regulatory relationships (ΕΚΜΕΑ registration, ΕΦΕΤ inspections κλπ.)
- **Risk appetite**: Πόσο conservative είναι ο πελάτης — αυτό διαμορφώνει το tone των interpretations
- **Prior interpretations** (αν υπάρχουν): 5-10 πραγματικά cases που έχει χειριστεί η νομική στο παρελθόν, με λύση

**Πώς χρησιμοποιείται**: Injected στο system prompt του interpretation engine ως background context. Αν αλλάζει το business (νέα εξαγορά, νέο business line), γίνεται refresh.

**Input 2 — Growing corpus of approved interpretations (progressive KB)**

Κάθε interpretation που περνά από `Draft → Approved` γίνεται μέρος του retrieval pool. Το σύστημα μαθαίνει τη γλώσσα και το reasoning style της νομικής ομάδας με τον χρόνο, μέσω:

- **RAG retrieval**: Πριν κάθε νέο interpretation, ανακτώνται 3-5 πιο σχετικά approved cases (topic + entity overlap)
- **Few-shot bank**: Οι reviewers μπορούν να σημαδεύουν approved interpretations ως "gold standard" — αυτά προωθούνται σε ξεχωριστό `Interpretation Examples` DB και χρησιμοποιούνται ως few-shot prompts για similar future cases
- **Style consistency**: Με τον χρόνο, οι νέες interpretations μοιάζουν όλο και περισσότερο με το πραγματικό writing style της ομάδας

**Timeline**:
- Μήνας 0-3: Το σύστημα λειτουργεί μόνο με το Client Context Document. Interpretations είναι πιο "textbook", γενικές. Reviewer edits είναι υψηλότερα.
- Μήνας 3-6: Corpus 50-100 approved interpretations. Retrieval αρχίζει να δίνει value. Edits πέφτουν.
- Μήνας 6+: Corpus 200+, καλή coverage. Interpretation quality πλέον προσεγγίζει το style του πελάτη.

**Alternative αν το Client Context Document δεν είναι εφικτό**: Ο πελάτης μπορεί να μας δώσει existing νομικά memos, past legal opinions, internal compliance policies — τα κάνουμε process σε embeddings και το retrieval pool ξεκινά από εκεί. Είναι λιγότερο ideal (πιο θόρυβος) αλλά functional.

---

## 9. Human-in-the-loop workflows

**Υλοποίηση**: Οι queue mechanics (assignment, SLA tracking, escalation) είναι deterministic logic στο Claude Code. Ο **Quality Observer Agent** (Claude Agent SDK) τρέχει weekly για metrics analysis, drift detection, και producing retros. Οι human reviewers δουλεύουν μέσα από Notion και μπορούν να καλέσουν Cowork agents ad-hoc — "Reclassify", "Explain Classification", "Similar Cases" — βλ. `cowork-agents.md`.

Το σύστημα έχει **τρεις workflows** όπου παρεμβαίνει άνθρωπος. Όλα διαχειρίζονται μέσα από το Notion με ξεχωριστές views. Το routing γίνεται με βάση expertise και workload.

### 9.1 Workflow 1 — Ambiguous relevance queue (Class C)

- **Trigger**: LLM classifier confidence 0.30-0.85 ή rule-based flag "human_review_required"
- **Notion view**: `Pending Relevance Review`
- **Assignment**: Round-robin σε νομική ομάδα, ή expertise-based (πχ όλα τα GDPR items → DPO)
- **SLA**: 2 εργάσιμες ημέρες
- **Reviewer actions**:
  - `Classify as A` → progresses σε interpretation engine
  - `Classify as B` → downgrade σε index-only, full text discarded από staging
  - `Update ontology` → ανοίγει request για ontology change (αν pattern εμφανίζεται)
- **Recorded fields**: Decision (A/B), Reason (dropdown: sector match / no impact / already covered / other), Reviewer name, Decision timestamp
- **Feedback loop**: Οι decisions ταΐζονται στο LLM classifier ως labeled examples για future retraining/few-shot updates

### 9.2 Workflow 2 — Interpretation review (Class A)

- **Trigger**: LLM produces interpretation, item enters `Draft` state
- **Notion view**: `Pending Interpretation Review`
- **Assignment**: Topic-based expertise routing (πχ CSRD → sustainability lawyer, ΕπΑντ → competition lawyer, GDPR → DPO)
- **SLA**: 3 εργάσιμες ημέρες standard, 24h για items flagged `action_signal = immediate`
- **Reviewer actions**:
  - `Approve as-is` → status becomes `Approved`
  - `Edit + Approve` → reviewer edits interpretation fields inline, marks approved. Edits tracked για training feedback.
  - `Reject + Redo` → item goes back με reviewer notes, LLM regenerates με το feedback ως additional context
  - `Escalate` → assigned σε senior lawyer ή εξωτερικό σύμβουλο
- **Recorded fields**: Reviewer, timestamp, edits diff (original vs approved), rejection reasons αν rejected

### 9.3 Workflow 3 — Client impact & action planning (post-approval)

- **Trigger**: Interpretation status = `Approved` AND `actions_required` is non-empty
- **Notion view**: `Requires Client Action`
- **Assignment**: Senior lawyer or compliance head
- **Actions**:
  - `No action needed` → archive
  - `Advise client team` → draft communication σε internal stakeholders
  - `Update internal policy` → link σε policy document that needs revision
  - `Track deadline` → automatic reminder before critical_dates.entry_into_force
  - `Escalate to management` → high-impact items
- **Optional integrations**: Asana/Trello για action tracking, Slack για alerts, calendar reminders για deadlines

### 9.4 Feedback loop για continuous improvement

**Weekly** (30' review meeting):
- Class C decisions που έγιναν: patterns που δείχνουν rule refinement
- Interpretation edits: fields που edit-άρονται συστηματικά → prompt tuning
- Missed items (surfaced by legal team από άλλες πηγές): coverage gaps

**Monthly**:
- Distribution shift Class A/B/C: αν αλλάζει σημαντικά, investigate γιατί
- Reviewer workload balance
- SLA compliance rate

**Quarterly**:
- Reclassification rate B→A (target: < 5%)
- Retrain classifier με τα labeled human decisions (αν local model) ή update few-shot examples (αν API model)
- Refresh rules based on quarterly patterns

### 9.5 Metrics — ορισμοί και targets

Όλα τα metrics υπολογίζονται με βάση **timestamps** που κρατούνται σε κάθε Notion page (§10):
- `Collected At` — auto από Notion Created time
- `Class C Assigned At` — όταν item mpainei σε review queue
- `Class C Decided At` — όταν reviewer αποφασίζει A/B
- `Draft Created At` — όταν LLM παράγει interpretation
- `Review Started At` — όταν reviewer ανοίγει το item
- `Reviewed At` — όταν status γίνεται Approved/Rejected

| Metric | Ορισμός | Target | Alert threshold |
|---|---|---|---|
| **Class C rate** | Class C items / total items (rolling 30-day) | < 15% | > 25% |
| **Interpretation approval-without-edits rate** | Approvals με μηδέν diff στα fields / total approvals | > 40% | < 20% |
| **Median time to interpretation approval** | Median (Reviewed At − Draft Created At), σε business hours | < 3 business days | > 5 days |
| **Reclassification B→A rate** | Items που άλλαξαν από B σε A / total B (quarterly) | < 5% | > 10% |
| **SLA compliance — relevance review** | % Class C items decided εντός 2 business days | > 90% | < 80% |
| **SLA compliance — interpretation review** | % Class A items reviewed εντός 3 business days | > 85% | < 75% |
| **Reviewer workload balance** | max(items assigned per reviewer) / mean(items assigned) — measure of imbalance | < 1.5 | > 2.0 |
| **Coverage — items expected vs. captured** | Πηγές που παρήγαγαν content / πηγές που έπρεπε να έχουν παράξει | > 95% | < 90% |

**SLA compliance rate — worked example**: Αν στον τελευταίο μήνα είχαμε 80 Class C items και 72 από αυτά ταξινομήθηκαν εντός 2 εργάσιμων → SLA compliance = 90%. Άριστο. Αν μόνο 60 → 75%, alert firing, ένδειξη understaffed queue.

**Reviewer workload balance — worked example**: Αν 3 reviewers έχουν 12 / 10 / 5 items στη queue τους, mean = 9, max = 12 → ratio = 1.33. Balanced. Αν 20 / 8 / 5 → mean = 11, max = 20 → ratio = 1.82. Alert — κάποιος πνίγεται.

---

## 10. Notion database schema (target for Phase 2)

**Structure**: 1 main database `Legal Intelligence` + 2 auxiliary databases (`Reviewers Workload`, `Ontology Reference`, `Interpretation Examples`).

Το schema είναι **class-aware** — τα πεδία που κρατάμε εξαρτώνται από το Content Class.

### 10.1 Legal Intelligence — main database

Οργανώνεται σε 4 property groups:

**Group 1 — Always populated** (A, B, C):

| Property | Type | Description |
|---|---|---|
| Title | Title | title field |
| Source ID | Text | source_id (CELEX / ΑΔΑ / decision number) |
| Source | Select | Source name (EUR-Lex / Δι@ύγεια / Βουλή / EDPB κ.λπ.) |
| Type | Multi-select | Regulation, Directive, Νόμος, ΠΔ, ΥΑ, Εγκύκλιος, Απόφαση, Γνωμοδότηση, Διαβούλευση, Ανάκληση |
| Authority | Select | Εκδούσα αρχή |
| Jurisdiction | Select | GR / EU / Other |
| Date Published | Date | date_published |
| Date Effective | Date | date_effective |
| Topics | Multi-select | Από ontology |
| Content Class | Select | A / B / C |
| Class Reasoning | Rich text | Γιατί ταξινομήθηκε |
| Confidence Score | Number | 0.0-1.0 |
| Original URL | URL | url — permanent link πίσω στην πηγή |
| Collected At | Created time | Auto |

**Group 2 — Full text present** (A + C only):

| Property | Type | Description |
|---|---|---|
| Full Text | Child page | Complete text (Notion child page αν > 2000 chars) |
| Language | Select | el / en / other |
| Snippet | Rich text | Πρώτα 500 chars — για list previews |

Για Class B, τα παραπάνω είναι **empty**. Ο URL δείχνει προς την επίσημη πηγή.

**Group 3 — Interpretation** (Class A only, after LLM run):

| Property | Type | Description |
|---|---|---|
| Summary | Rich text | Plain-language summary |
| What Changed - Before | Rich text | State before |
| What Changed - After | Rich text | State after |
| What Changed - Delta | Rich text | Key differences |
| Business Lines Affected | Multi-select | tobacco_wholesale / food_wholesale / food_retail / franchise / cross_functional |
| Support Functions Affected | Multi-select | legal / compliance / hr / it / operations / finance |
| Operational Impact | Rich text | Day-to-day impact |
| Compliance New Obligations | Rich text | New requirements |
| Compliance Lifted Obligations | Rich text | Requirements no longer applicable |
| Actions Required | Child page | List of actions με owners & deadlines |
| Entry Into Force | Date | Critical date |
| Transition End | Date | If applicable |
| Reporting Deadlines | Rich text | Serialized dates |
| Cited Articles | Rich text | Article refs + excerpts |
| Related Events | Relation | Links σε άλλες σελίδες (precedents) |
| Requires Specialist Review | Checkbox | LLM flag |
| Specialist Domain | Select | gdpr / competition / tax / food_safety / labor / other |
| Confidence Notes | Rich text | Uncertainty areas |

**Group 4 — Review workflow** (populated during human review):

| Property | Type | Description |
|---|---|---|
| Interpretation Status | Select | Draft / Under Review / Approved / Rejected |
| Reviewer | Person | Νομικός που κάνει review |
| Review Started At | Date | |
| Review Completed At | Date | |
| Review Notes | Rich text | Comments/edits από reviewer |
| Client Action Status | Select | None / Advise / Update Policy / Track Deadline / Escalated / Done |
| Action Owner | Person | Internal client contact |
| Action Deadline | Date | |
| Reclassify Requested | Checkbox | Flag για B→A reclassification |

### 10.2 Views

1. **Recent items** — All items, sorted by Date Published DESC, grouped by Content Class
2. **Pending Relevance Review** — Filter: Content Class = C AND Reviewer = current user OR unassigned
3. **Pending Interpretation Review** — Filter: Content Class = A AND Interpretation Status = Draft
4. **Approved & Actionable** — Filter: Interpretation Status = Approved AND Client Action Status ≠ None/Done
5. **By Topic** — Grouped by Topics, useful για topic-based exploration
6. **Critical Deadlines** — Filter: Any Deadline field within next 90 days, sorted asc
7. **Index Archive** — Class B items, minimal display (just title/date/source/url) — for occasional keyword search only
8. **My Queue** — Filter: Reviewer = current user AND Status in (Draft, Under Review)

### 10.3 Auxiliary databases

**Reviewers Workload**:
- Reviewer (Person, unique)
- Current queue depth (rollup από Legal Intelligence)
- Avg time to review (rollup)
- Areas of expertise (Multi-select — mapping σε topics)
- Available (Checkbox — for out-of-office handling)
- Max concurrent items (Number — για load balancing)

**Ontology Reference**:
- Το ontology από §4 mirrored στο Notion για easy consultation από τη νομική ομάδα.
- Topic ID (Title), Name GR/EN, Domain, Keywords GR/EN, Priority, Sample Items (Relation σε Legal Intelligence)

**Interpretation Examples**:
- Curated από τη νομική ομάδα ως gold-standard examples για few-shot learning.
- Topic (Relation), Original Item (Relation), Interpretation (Rich text), Notes (Rich text), Added by (Person), Date

### 10.4 Sync mechanism

- **Notion API** με batch inserts (max 100 items ανά batch)
- **Rate limit**: 3 req/sec — respect strictly
- **Rich text > 2000 chars** → Notion child page (μπλοκ)
- **Full text > 100KB** → attachment file
- **Bidirectional sync**: Οι reviewer edits στο Notion φτάνουν πίσω στη normalized DB κάθε 15 λεπτά (webhook αν είναι εφικτό, αλλιώς polling)

---

## 11. Adding a new source — playbook for legal team

Όταν η νομική ομάδα εντοπίζει νέα πηγή που θέλει να συμπεριληφθεί, ακολουθεί το ακόλουθο playbook:

### Step 1 — Source assessment

Συμπλήρωσε το ακόλουθο template:

```yaml
source_name: ""              # Π.χ. "ΓΓΠΣΨΔ - Ανακοινώσεις"
url: ""
domain: ""                   # Ποιο compliance domain καλύπτει
priority: ""                 # high/medium/low
expected_volume: ""          # #items/month
languages: []                # ["el"], ["en"], κ.λπ.
integration_type: ""         # "api" / "rss" / "scraping" / "manual"
authentication_required: false
public_documentation_url: "" # Αν υπάρχει tech docs
similar_existing_source: ""  # Αν υπάρχει analog που ήδη έχουμε
notes: ""
```

### Step 2 — Integration classification

Ρώτησε (ή έλεγξε τεχνικά):

1. **Υπάρχει επίσημο API;** → Tier 1
2. **Υπάρχει RSS/Atom feed;** → Tier 1
3. **Είναι στη Δι@ύγεια ως authority;** → Tier 1 μέσω Δι@ύγειας
4. **Πρέπει να scraping;** → Tier 2
5. **Είναι newsletter/commercial;** → Tier 3

### Step 3 — Ontology impact review

Ελέγξτε:
- Καλύπτει η νέα πηγή existing topic ή νέο;
- Αν νέο topic → append στο `ontology.yaml` με keywords
- Αν existing topic → confirm ότι η πηγή θα κάνει flag για το ίδιο tag

### Step 4 — Hand-off to engineering

Δώστε στη REBORRN ή στο technical team:
- Το συμπληρωμένο template του Step 1
- Ενδεικτικά sample outputs από την πηγή (5-10 items)
- SLA expectations (πόσο γρήγορα πρέπει να εμφανίζεται νέο item στο Notion)

### Step 5 — Test window

Πριν production activation:
- 2 εβδομάδες shadow-run — το νέο source γράφει στο staging DB, όχι στο Notion
- Νομική ομάδα κάνει review 10 τυχαία items για accuracy
- Sign-off → promotion σε production

### Step 6 — Ongoing monitoring

- Έλεγχος quarterly ότι η πηγή ακόμα υπάρχει, ακόμα έχει σχετικό content, ακόμα λειτουργεί το integration
- Αν η πηγή σιωπήσει για >30 μέρες, alert στο νομικό τμήμα (μπορεί να έχει αλλάξει URL ή να έχει κλείσει)

---

## 12. Operational considerations

### Rate limiting & discretion

- Πάντα respect robots.txt
- **User-Agent**: Rotating pool από generic browser user-agents (πχ πραγματικά Chrome/Firefox strings). **Όχι** identifiable branding σε καμία περίπτωση — δημιουργεί ρίσκο εντοπισμού/blocking και εκθέτει τον πελάτη.
- **Rate limit**: Max 1 req / 5 sec ανά domain για scraping (πιο συντηρητικό από το industry standard 1/2sec — mείωσε ρίσκο rate-limit από publisher side)
- **Jittered delays**: Πρόσθεσε ±30% randomness στο κάθε delay για να μη δείχνει σαν bot
- **Circuit breaker**: Αν εντοπίσει 3+ 429/503 από ίδιο domain εντός 5 λεπτών, pause 30 λεπτά αυτόματα
- **Exponential backoff** σε 429/503: 2s, 4s, 8s, 16s, 32s
- **Concurrent requests per domain**: max 1 — sequential για politeness
- **Headers**: normal browser headers (Accept, Accept-Language: `el,en;q=0.9`, referrer αν είναι εύλογο)

### Error handling

- **Transient errors** (5xx, timeouts): retry με backoff, max 5 attempts
- **Permanent errors** (404, schema change): alert + skip item + log για human review
- **Selector breakage** (Tier 2): auto-alert στο ops channel, human-in-the-loop για fix

### Logging & observability

- Structured logs (JSON) με fields: `source`, `event`, `status`, `duration_ms`, `error`
- Metrics: items/day per source, dedup rate, tagging coverage, latency source→Notion
- Weekly report στο νομικό τμήμα: "τι μπήκε, τι δεν μπήκε, τι έσπασε"

### Data quality checks

- Ποσοστό items με empty title / date / URL — should be < 1%
- Ποσοστό items με assigned topic — should be > 90%
- Duplicate detection rate — track baseline, alert αν spike

### Retention

- Raw payloads: κρατάμε 12 μήνες για audit
- Normalized data: indefinite
- Πλήρες κείμενο νομοθεσίας: indefinite (public info)
- Class B index-only: indefinite (minimal footprint)
- Class C staging full text: 7 days TTL (§7.6)

### GDPR compliance για το ίδιο το σύστημα

- Legal basis για επεξεργασία: legitimate interest (νομική συμμόρφωση εταιρείας)
- Δεν επεξεργαζόμαστε personal data εκτός από ονόματα δικηγόρων/δικαστών που είναι already public στις αποφάσεις
- Data subject rights: αν κάποιος ζητήσει διαγραφή, έχουμε process (εντοπισμός + delete + confirm)

### Cost tracking & optimization

Η νομική intelligence platform έχει μεταβλητό cost profile — LLM calls, third-party APIs, storage, Notion API quota. Χρειάζεται visibility per component για ορθολογική διαχείριση.

**Instrumentation**:

Κάθε LLM call καταγράφει σε `cost_ledger` table (ή Notion DB):
- `timestamp`
- `stage` — one of: `topic_tagging`, `relevance_classify`, `interpretation`, `interpretation_retrieval`
- `model` — Sonnet/Opus/Haiku/etc.
- `input_tokens`
- `output_tokens`
- `usd_cost` — computed από current pricing (πίνακας σε config για easy update)
- `item_id` — link στο source item για traceability
- `success` — boolean

**Cost report — monthly** (auto-generated σε Notion):

| Component | Cost/month | % total | Trend | Notes |
|---|---|---|---|---|
| LLM — topic tagging | ... | ... | ... | ~500 tokens/item, Sonnet |
| LLM — relevance classification | ... | ... | ... | ~800 tokens/item, Sonnet |
| LLM — interpretation (Sonnet) | ... | ... | ... | ~3000 tokens/item, Class A only |
| LLM — interpretation (Opus escalation) | ... | ... | ... | ~5% items |
| LLM — retrieval augmentation embeddings | ... | ... | ... | |
| Notion API | ... | ... | ... | Free tier limits |
| Storage (Postgres/S3 αν Path A) | ... | ... | ... | |
| Third-party APIs (πχ Apitalks RASFF wrapper) | ... | ... | ... | |
| Infra (compute, orchestration) | ... | ... | ... | |
| Text extraction (Tika) | ... | ... | ... | |
| **Total** | ... | 100% | | |

**Cost benchmarks** (indicative — validate με actual pricing):

Ενδεικτικά για βάση 800 items/μήνα με 25% Class A rate:
- Topic tagging: 800 × 500 tokens = 400k tokens × Sonnet input pricing ≈ $1.2/μήνα
- Relevance classification (only για items που περνάν από LLM, ~60%): 480 × 800 tokens ≈ $1.2/μήνα
- Interpretation (Class A, ~200 items): 200 × 3000 tokens output = 600k output tokens × Sonnet output pricing ≈ $9/μήνα
- Interpretation Opus escalation (~10 items): 10 × 5000 tokens ≈ $2/μήνα
- Notion API: free tier probably sufficient

**Rough estimate για MVP με Path B**: $15-30/μήνα LLM + Notion free tier + minimal compute. **Very manageable**, δεν είναι φραγμός.

**Optimization levers**:

Αν το κόστος γίνει issue:
1. **Downgrade tagging model σε Haiku** — 5-10x cheaper, small quality impact
2. **Cache classifier responses** για similar items (semantic dedup upstream)
3. **Batch topic tagging** — bulk items σε ενιαίο call
4. **Skip Opus escalation** — αν quality με Sonnet είναι acceptable
5. **Prompt compression** — αφαίρεση redundant context από system prompts
6. **Truncate long documents** — για items > 20k tokens, χρησιμοποίησε summary πριν το LLM call

**Alert thresholds**:
- Monthly cost > 2x baseline → investigate
- Single item cost > $1 → investigate (probably infinite loop ή token bloat)
- Failed LLM call rate > 5% → alert

---

## 13. Compliance & ethics notes

- **Copyright:** Οι νόμοι/αποφάσεις δημοσίων φορέων είναι public domain στην ΕΕ. Newsletters/commentary από δικηγορικά γραφεία & commercial providers ΕΧΟΥΝ copyright — τα κρατάμε σε internal use, δεν τα αναπαράγουμε αυτούσια.
- **Attribution:** Πάντα κρατάμε την επίσημη πηγή link και την εμφανίζουμε στο Notion για traceability.
- **Terms of Service:** Πριν activation κάθε πηγής, review του ToS. Ειδικά για Tier 3 (commercial), respect των terms of automated processing.
- **Fair use commercial content:** Newsletters από commercial vendors → μόνο internal circulation, μόνο για compliance purposes.

---

## Appendix A — Deployment checklist

### Phase 1 — Collection layer

- [ ] Ontology.yaml drafted από legal team
- [ ] Ontology.yaml validated σε workshop (90')
- [ ] Relevance_rules.yaml drafted (include/exclude rules)
- [ ] Staging DB provisioned
- [ ] Normalized DB provisioned + schema migrations
- [ ] Ingestion workers deployed (Tier 1 sources)
- [ ] Scrapers deployed (Tier 2 sources)
- [ ] Email inbox setup for Tier 3
- [ ] Scheduler configured (Prefect/Airflow/n8n)
- [ ] Monitoring dashboards live
- [ ] Alerting configured (Slack/email)
- [ ] First 2-week shadow run completed
- [ ] Legal team sign-off on collection data quality

### Phase 2 — Triage, interpretation & review

- [ ] Relevance triage rules validated με legal team
- [ ] LLM classifier prompt tested σε golden set (100 items pre-labeled από legal)
- [ ] Classifier confidence thresholds calibrated
- [ ] Class C (ambiguous) volume measured — target < 15%
- [ ] Interpretation engine prompt & structured schema validated
- [ ] Interpretation examples DB seeded με 10-15 gold-standard cases
- [ ] Human reviewer roster defined με expertise areas
- [ ] SLAs για κάθε workflow agreed
- [ ] Notion database created με όλες τις views
- [ ] Notion sync active με class-aware payloads
- [ ] Bidirectional sync (Notion → DB) validated
- [ ] Reviewer training session (60') για workflows 1/2/3
- [ ] Feedback loop cadence agreed (weekly/monthly/quarterly)
- [ ] First 4-week production run με weekly retros

### Phase 3 — Optimization (post-launch)

- [ ] Monthly metrics dashboard review
- [ ] Rule refinement based on Class C patterns
- [ ] Prompt tuning based on interpretation edit patterns
- [ ] Ontology updates based on missed items
- [ ] Documentation handed off to internal ops

---

## Appendix B — Suggested tech stack (indicative)

| Layer | Recommended | Alternative |
|---|---|---|
| Orchestration | Prefect | Airflow, n8n |
| Ingestion workers | Python (async httpx) | Node.js |
| Scraping | Playwright | Selenium, Puppeteer |
| Staging DB | PostgreSQL 16 | — |
| Text extraction | Apache Tika | pdfplumber, unstructured.io |
| LLM topic tagging | Claude Sonnet | OpenAI, local (Ollama) |
| LLM relevance classifier | Claude Sonnet | OpenAI, fine-tuned local |
| LLM interpretation (default) | Claude Sonnet | GPT-4-class |
| LLM interpretation (escalation) | Claude Opus | — |
| Retrieval augmentation | pgvector on PostgreSQL | Pinecone, Weaviate |
| Notion sync | Notion API (Python SDK) | — |
| Monitoring | Grafana + Prometheus | Datadog |
| Human queue mgmt | Notion views | Linear, Jira, custom |
| Secrets | HashiCorp Vault | AWS Secrets Manager |
| Feedback storage (labeled data) | PostgreSQL + Notion mirror | — |

---

## Appendix C — Contact & escalation

| Role | Contact |
|---|---|
| Client legal lead | [name] — [email] |
| REBORRN project lead | Antonis — [email] |
| REBORRN engineering | [name] |
| Data quality issues | Slack #legal-intel |
| Source additions | Fill template §11, send to REBORRN engineering |

---

**End of document.**
