# Cowork Agents — Legal Team Toolkit

**Έκδοση:** 1.0
**Companion document:** `instructions.md` (Claude Code build)
**Environment:** Cowork
**Users:** Νομική ομάδα του πελάτη

---

## 1. Τι είναι αυτό το document

Αυτό το αρχείο περιγράφει τους **on-demand agents** που θα ζουν στο Cowork environment και θα καλούνται από τη νομική ομάδα του πελάτη ad-hoc. Είναι **complement** στο κύριο production σύστημα που περιγράφεται στο `instructions.md` (Claude Code build) — όχι αντικατάσταση.

**Διαχωρισμός με μία γραμμή:**
- **Claude Code** = "τι τρέχει αυτόματα κάθε μέρα, μαζεύει την πληροφορία, ταξινομεί, ερμηνεύει"
- **Cowork** = "τι μπορεί να καλέσει η νομική σύμβουλος όταν χρειάζεται να σκάψει βαθύτερα ή να παράξει κάτι specific"

**Interface**: Και τα δύο environments διαβάζουν/γράφουν από το ίδιο Notion database. Οι Cowork agents ξέρουν το Notion schema (από `instructions.md` §10) και μπορούν να το queryτις, να το ενημερώσουν, ή να δημιουργήσουν νέες σελίδες.

---

## 2. Design principles για κάθε Cowork agent

Πριν τους individual specs, μερικές κοινές αρχές:

**Conversational, όχι programmatic.** Ο κάθε agent σχεδιάζεται για natural language interaction. Η νομική σύμβουλος δεν πρέπει να ξέρει τεχνικές παραμέτρους — δίνει context και ζητά, ο agent αναλαμβάνει.

**Grounded στο ίδιο data.** Ο κάθε agent έχει access στο Notion database και στο Client Context Document. Δεν κάνει web scraping ή external retrieval — δουλεύει με ό,τι έχει ήδη μαζέψει το production σύστημα.

**Αναφέρει τις πηγές του.** Όποτε ένας agent παραπέμπει σε κάτι (νόμος, απόφαση, προηγούμενη ερμηνεία), δείχνει link στο Notion page για traceability.

**Δεν παρακάμπτει το review workflow.** Αν ένας Cowork agent παράγει draft interpretation ή client communication, αυτό μπαίνει σε status `Draft` — πρέπει human approval πριν χρησιμοποιηθεί.

**Cost-aware.** Ο κάθε agent καταγράφει tokens/cost στο cost ledger του Claude Code σύστημα, με tag `source: cowork_[agent_name]`. Έτσι κρατάμε visibility ακόμα και σε ad-hoc usage.

**Ίδιο disclaimer.** Κάθε output φέρει: *"Παράγεται αυτόματα, υπόκειται σε νομική επικύρωση, δεν αποτελεί νομική συμβουλή."*

---

## 3. Οι 8 Cowork agents

### 3.1 Explain Classification Agent

**Purpose**: Εξηγεί γιατί ένα item ταξινομήθηκε σε συγκεκριμένη κλάση (A/B/C) και τι θα άλλαζε την ταξινόμηση.

**Χρησιμοποιείται όταν**: 
- Η νομική σύμβουλος βλέπει ένα Class B item που της φαίνεται σχετικό
- Ή ένα Class A item που της φαίνεται άσχετο
- Ή γενικά θέλει να καταλάβει τη λογική του Triage Agent

**Typical prompt από τη νομική σύμβουλο**:
> "Ρίξε μια ματιά στο [Notion URL] — γιατί το ταξινόμησε ως Class B; Μου φαίνεται ότι επηρεάζει το food business μας."

**Τι κάνει ο agent**:
1. Fetches το Notion item + το reasoning field που έγραψε ο Triage Agent
2. Fetches το Client Context Document + το relevant sub-section του ontology
3. Παράγει explanation σε τρία μέρη:
   - Τι rules/keywords/signals οδήγησαν στην απόφαση
   - Τι θα έπρεπε να ισχύει διαφορετικά για να αλλάξει η κλάση
   - Τι εναλλακτικές interpretations υπάρχουν, με confidence
4. Προτείνει: "Αν θέλεις να το reclassify, καλώ τον Reclassify Agent με τα ακόλουθα updates"

**Output**: Conversational explanation + link στο original Notion page + optional handoff στον Reclassify Agent

**Cost profile**: Χαμηλό — μία-δύο LLM calls per invocation

---

### 3.2 Reclassify Agent

**Purpose**: Επαναταξινομεί ένα item με βάση human input, ενημερώνοντας το Notion.

**Χρησιμοποιείται όταν**:
- Η νομική σύμβουλος έχει αποφασίσει ότι κάτι έπρεπε να είναι διαφορετική κλάση
- Ειδικά για B → A reclassifications που απαιτούν re-fetch full text από την πηγή

**Typical prompt**:
> "Το item [Notion URL] είναι εσφαλμένα Class B. Το θέλω Class A γιατί επηρεάζει τη γραμμή HORECA. Παρακαλώ reprocess."

**Τι κάνει ο agent**:
1. Fetches το Notion item
2. Αν είναι B → A: καλεί τη Claude Code re-fetch API για full text από την πηγή
3. Ενημερώνει το status σε `Class A - Awaiting Interpretation` — αυτό ενεργοποιεί τον production Interpretation Agent
4. Γράφει αιτιολογία στο Reason field ("reclassified by [reviewer] on [date] because [feedback]")
5. Αν το pattern εμφανίζεται συχνά ("έχεις πει τα τελευταία 5 items σε αυτό το topic ότι έπρεπε A"), προτείνει ontology/rule update

**Output**: Confirmation ότι το item promoted + link + suggestion για rule update αν εντοπίζεται pattern

**Cost profile**: Χαμηλό. Το πιο ακριβό κομμάτι (interpretation) γίνεται στη συνέχεια από τον production Interpretation Agent.

---

### 3.3 Similar Cases Agent

**Purpose**: Δεδομένου ενός item, βρίσκει σχετικά items στο database — για να δει η νομική σύμβουλος το ιστορικό context.

**Χρησιμοποιείται όταν**:
- Η νομική σύμβουλος θέλει να δει "τι έχουμε ξαναδεί σε αυτό το θέμα"
- Έρχεται νέος νόμος που τροποποιεί παλαιότερο — θέλει το προηγούμενο νομοθετικό status
- Παράγει memo και θέλει precedents

**Typical prompt**:
> "Έχει έρθει νέα ΥΑ για το labeling αλλεργιογόνων [Notion URL]. Δείξε μου όλα τα σχετικά items των τελευταίων 3 ετών."

**Τι κάνει ο agent**:
1. Fetches το reference item + topics + keywords
2. Queryάρει το Notion database:
   - Same topic tags (broad match)
   - Same authority
   - Related topic tags (from ontology)
   - Semantic similarity (αν έχει pgvector-like retrieval available, αλλιώς keyword-based)
3. Ranks by relevance και presents:
   - 5-10 πιο σχετικά items
   - Για κάθε ένα: τίτλος, ημερομηνία, class, μία γραμμή relevance rationale
   - Timeline view (chronological)
4. Optionally: παράγει σύντομο "state of the topic" summary — πώς εξελίχθηκε το regulatory landscape

**Output**: List με clickable Notion links + optional timeline summary

**Cost profile**: Χαμηλό-μέτριο. Retrieval-heavy, αλλά χωρίς μεγάλα LLM generations.

---

### 3.4 Deep Dive Agent

**Purpose**: Παράγει εκτενέστερη νομική ανάλυση από τη standard interpretation, για high-complexity items.

**Χρησιμοποιείται όταν**:
- Η standard interpretation δεν επαρκεί
- Item είναι CSRD/CBAM/άλλο πολύπλοκο EU regulation
- Item έχει significant client impact
- Ο reviewer έχει flag `requires_specialist_review = true`

**Typical prompt**:
> "Θέλω deep dive στο [CSRD item Notion URL]. Δώσε μου: full applicability analysis για την εταιρεία μας, gap analysis με το τρέχον reporting, roadmap για compliance."

**Τι κάνει ο agent**:
1. Fetches το full text του item + standard interpretation
2. Fetches το Client Context Document
3. Fetches όλα τα approved interpretations σε related topics
4. Fetches related items (via Similar Cases logic)
5. Παράγει expanded analysis με sections:
   - Legal type & scope determination (rigorous)
   - Applicability analysis to client (KAD-by-KAD, business-line-by-business-line)
   - Gap analysis (τι κάνει σήμερα ο πελάτης vs τι πρέπει)
   - Risk assessment (πιθανά προστίμα, reputational, operational)
   - Compliance roadmap (phased actions με deadlines)
   - Open questions (πράγματα που θέλουν external counsel)
6. Χρησιμοποιεί **Claude Opus** αντί για Sonnet — καλύτερη quality για complex reasoning

**Output**: Long-form memo (~2000-3000 λέξεις) σε νέα Notion child page κάτω από το item, με status `Draft - Requires Review`

**Cost profile**: Υψηλό — Opus + long input context + long output. Ενδεικτικά $2-5 per invocation.

**Guardrail**: Ο agent ζητά explicit confirmation πριν τρέξει ("Θα κοστίσει ~$3 και θα πάρει 1-2 λεπτά. Confirm;") για να αποφύγει accidental heavy usage.

---

### 3.5 Client Communication Draft Agent

**Purpose**: Draftάρει internal client communication (email, memo, Slack message) για ένα approved Class A item.

**Χρησιμοποιείται όταν**:
- Interpretation έχει status `Approved` και requires stakeholder awareness
- Ο ίδιος reviewer θέλει να ενημερώσει internal audience (management, HR, IT, compliance officers)

**Typical prompt**:
> "Στείλε ένα draft email στην ομάδα HR για το item [Notion URL] — αφορά νέες υποχρεώσεις γύρω από personal data τους εργαζομένους. Formal tone. 200-300 λέξεις."

**Τι κάνει ο agent**:
1. Fetches το item + approved interpretation + actions_required
2. Ρωτά για parameters που δεν είναι σαφή:
   - Audience (HR / IT / Compliance / Management / Franchisees / Board)
   - Channel (email / Slack / formal memo)
   - Tone (formal / conversational / urgent)
   - Length constraint
   - Deadline urgency
   - Signatory (Νομική / GC / Compliance officer)
3. Παράγει draft με proper structure:
   - Subject / heading
   - Executive summary (2-3 γραμμές)
   - Τι άλλαξε
   - Τι σημαίνει για τους παραλήπτες specifically
   - Τι απαιτείται να κάνουν
   - Deadlines
   - Contact για ερωτήσεις
4. Προσαρμόζει tone/vocabulary στον audience

**Output**: Draft message ως Notion child page + optional export σε email format

**Cost profile**: Χαμηλό-μέτριο

---

### 3.6 Policy Update Draft Agent

**Purpose**: Δεδομένου ενός item που τροποποιεί existing internal policy, drafts τη σχετική αλλαγή.

**Χρησιμοποιείται όταν**:
- Approved Class A item έχει `Client Action Status = Update Policy`
- Ο νομικός/compliance officer πρέπει να ενημερώσει internal document

**Typical prompt**:
> "Το item [Notion URL] απαιτεί update στην Data Retention Policy μας. Επισυνάπτω την τρέχουσα policy — δώσε μου track-changes version που ενσωματώνει τις νέες απαιτήσεις."

**Τι κάνει ο agent**:
1. Fetches το item + interpretation
2. Ζητά την τρέχουσα policy (upload/paste στη συνομιλία)
3. Παράγει redlined version με:
   - Explicit additions (highlighted)
   - Explicit deletions (strikethrough)
   - Justification σε margin comments (γιατί κάθε αλλαγή)
   - Cross-references στο source item
4. Highlights sections που θέλουν human judgment

**Output**: Redlined document + change log + list από outstanding decisions

**Cost profile**: Μέτριο

---

### 3.7 Ontology Refinement Assistant

**Purpose**: Chat interface για τη νομική ομάδα να προτείνει και να δοκιμάσει ontology changes.

**Χρησιμοποιείται όταν**:
- Weekly retros δείχνουν patterns σε mis-classification
- Νέο business line ή sector shift
- Ο reviewer θέλει να δει impact από proposed ontology change

**Typical prompt**:
> "Θέλω να προσθέσω νέο topic 'e-cigarettes ρύθμιση' με keywords X, Y, Z. Δείξε μου τι items από τα τελευταία 6 μήνες θα άλλαζαν classification."

**Τι κάνει ο agent**:
1. Παίρνει το proposed change (νέο topic, τροποποίηση keywords, νέο rule)
2. Simulates την αλλαγή σε subset του Notion database (last 6 μήνες)
3. Reports:
   - Πόσα items θα re-classified
   - Ποιοι θα ήταν τα specific items (5-10 samples)
   - Πόσα false positives/negatives φαίνονται
4. Αν το change φαίνεται sound, προσφέρει "shall I update ontology.yaml?" με proper git-style commit message
5. Αν όχι, εξηγεί γιατί και προτείνει refinements

**Output**: Impact analysis + optional automated ontology.yaml update (πηγαίνει σε PR για human approval)

**Cost profile**: Μέτριο — retrieval-heavy

**Guardrail**: Ontology updates γίνονται μόνο μέσω PR στο repo, όχι direct writes. Ο agent προτείνει, ο άνθρωπος approves.

---

### 3.8 Weekly Digest Agent

**Purpose**: Παράγει curated weekly summary για stakeholders — νομική ομάδα, GC, C-level.

**Χρησιμοποιείται όταν**:
- Manual trigger κάθε Δευτέρα πρωί
- Ή scheduled inside Cowork για regular runs

**Typical prompt**:
> "Δώσε μου το weekly digest για την προηγούμενη εβδομάδα, στοχεύοντας C-level audience (short, high-impact only)."

**Τι κάνει ο agent**:
1. Queries Notion για items collected/approved στις τελευταίες 7 μέρες
2. Filters by:
   - Status = Approved
   - Priority = high/medium
   - Business impact significant
3. Categorizes:
   - Νέες υποχρεώσεις που απαιτούν immediate action
   - Deadlines coming up σε 30-60-90 μέρες
   - Regulatory trends (πχ EU push σε ESG)
   - Notable court decisions
4. Παράγει digest σε τρεις εκδόσεις:
   - Short (C-level): 5 bullet points
   - Medium (GC): 1 σελίδα
   - Full (νομική ομάδα): 2-3 σελίδες με details

**Output**: 3 versions του digest σε Notion + optional email export

**Cost profile**: Μέτριο. Weekly cadence κρατά το total cost low.

---

## 4. Πώς να ξεκινήσεις με τους Cowork agents

**Φάση 1 — Build sequence** (recommended order):

1. **Explain Classification Agent** — Ο πιο απλός, καλό warm-up για το legal team να νιώσει με το Cowork
2. **Similar Cases Agent** — Άμεσα useful, χαμηλό cost
3. **Reclassify Agent** — Σε στενή σύνδεση με το Explain Classification
4. **Weekly Digest Agent** — Regular cadence, δείχνει value σε management
5. **Client Communication Draft Agent** — Concrete productivity boost
6. **Deep Dive Agent** — Για high-complexity cases
7. **Policy Update Draft Agent** — Όταν αρχίζουν να έρχονται actionable items
8. **Ontology Refinement Assistant** — Αφού συγκεντρωθεί κάποιο ιστορικό data για meaningful simulation

**Prerequisites**: Πριν τα Cowork agents έχει νόημα να τρέξουν, πρέπει το Claude Code σύστημα να έχει:
- Notion database populated με τουλάχιστον 100-200 items
- Client Context Document uploaded
- Ontology & relevance rules deployed
- Working Triage + Interpretation agents

Αν το legal team ξεκινήσει να χρησιμοποιεί Cowork agents σε empty Notion, το experience θα είναι απογοητευτικό.

---

## 5. Setup instructions για κάθε agent σε Cowork

Για κάθε agent, ένα Cowork "space" με:

### 5.1 System context (κοινό για όλους)

```
Είσαι agent στο Legal Intelligence system της [company name].

CONTEXT:
- Η εταιρεία είναι χονδρικός έμπορος καπνικών και τροφίμων, με 
  franchise retail food-service. KAD codes: 46.35, 46.37, 46.38, 
  56.10, 56.30.
- Νομικό τμήμα σε: [country/city]
- Το production σύστημα (Claude Code) μαζεύει, ταξινομεί, και 
  ερμηνεύει νομικά items από ~15 πηγές.
- Το Notion database "Legal Intelligence" είναι το single source 
  of truth. Πρόσβαση: [Notion API token, connected via Cowork].
- Το Client Context Document: [Notion page URL]
- Το Ontology reference: [Notion database URL]

ΑΡΧΕΣ:
- Απαντάς στα Ελληνικά (εκτός αν ζητηθεί άλλη γλώσσα)
- Πάντα αναφέρεις sources με Notion links
- Δεν παράγεις τελικές νομικές συμβουλές — draft με disclaimer
- Καταγράφεις usage στο cost ledger (tag: cowork_[agent_name])
- Αν κάτι υπερβαίνει το scope σου, redirect στον σωστό agent ή στο Claude Code σύστημα
```

### 5.2 Agent-specific instructions

Για κάθε agent, θα φτιάξουμε ξεχωριστά system prompts που θα κρατούν το core context παραπάνω και θα προσθέτουν agent-specific behavior. Παραδείγματα:

**Explain Classification Agent**:
```
[Core context παραπάνω +]

ΡΟΛΟΣ: Εξηγείς γιατί συγκεκριμένα items ταξινομήθηκαν σε A/B/C.

ΡΟΗ:
1. Λαμβάνεις Notion URL από τον χρήστη
2. Fetch το item metadata + reasoning field
3. Fetch relevant ontology entries και relevance_rules που ίσχυσαν
4. Παράγεις explanation σε τρία μέρη:
   - Τι rules/signals ενεργοποιήθηκαν
   - Τι θα άλλαζε το outcome
   - Alternative interpretations με confidence
5. Αν ο χρήστης δεν συμφωνεί, προσφέρεις handoff στον Reclassify Agent

TOOLS διαθέσιμα σε σένα:
- notion.query_page(url)
- notion.query_database(filters)
- fs.read_ontology()
- fs.read_relevance_rules()
- cost_ledger.log(tokens, cost, tag)
```

Ανάλογα για κάθε άλλο agent.

---

## 6. Governance & guardrails

### 6.1 Άδεια πρόσβασης στο Notion

Οι Cowork agents χρειάζονται Notion API access. Παρέχεται μέσω:
- Ένα Notion integration token με **read-write** στο Legal Intelligence database + **read-only** στο Ontology
- Δεν έχουν πρόσβαση σε άλλα Notion databases του πελάτη

### 6.2 Human approval για destructive actions

Cowork agents ΔΕΝ κάνουν αυτόνομα:
- Reclassifications (ναι, ο Reclassify Agent το προτείνει, αλλά χρειάζεται explicit "confirm" από τον χρήστη πριν εκτελέσει)
- Ontology updates (πάντα μέσω PR — ο agent προτείνει, δεν εκτελεί)
- Deletion κανενός item

### 6.3 Cost caps

Κάθε agent έχει monthly budget cap. Αν εξαντληθεί:
- Warning σε 80%
- Hard stop σε 100% — απαιτείται manual override από REBORRN/GC
- Deep Dive Agent έχει και per-invocation cap για να αποφύγουμε runaway

### 6.4 Audit trail

Κάθε invocation ενός Cowork agent καταγράφεται:
- Who invoked
- When
- What was the input
- What was the output
- Tokens & cost

Trailing 90 days audit log διαθέσιμο σε GC.

### 6.5 Data privacy

Οι Cowork agents δεν εξάγουν data εκτός του Cowork/Notion perimeter. Δεν postάρουν σε external APIs πέρα από τα Anthropic API calls για inference.

---

## 7. Success metrics για το Cowork layer

Θα ξέρουμε ότι δουλεύει καλά όταν:

| Metric | Target |
|---|---|
| Weekly active νομικοί που χρησιμοποιούν Cowork | > 60% της ομάδας |
| Reclassification requests μέσω Cowork | αντικαθιστούν manual updates |
| Client communications που φύγανε με Cowork draft | > 40% |
| Deep Dive invocations / μήνα | 5-10 (δείχνει ότι χρησιμοποιείται για high-complexity, όχι για routine) |
| Ontology refinements μέσω Assistant | > 1/μήνα (δείχνει ζωντανή διαχείριση) |
| Feedback από νομικούς σε NPS-style survey | > 40 |

Αν πέσουν κάτω από targets σε 3 μήνες — probably είτε τα agents δεν χτίζουν pull, είτε το UX του Cowork δεν συνεργάζεται με τη ροή τους. Recalibrate.

---

## 8. Επόμενα βήματα

1. **Wait for Phase 3+** του Claude Code build ώστε Notion να έχει meaningful data
2. **Prototype με 1-2 agents** πρώτα (Explain Classification + Similar Cases) — validate με 2-3 νομικούς
3. **Iterate σε prompts** based on real feedback
4. **Roll out σταδιακά** — προσθέτουμε 1-2 agents/εβδομάδα
5. **Weekly retros** τους πρώτους 2 μήνες για fine-tuning

**End of document.**
