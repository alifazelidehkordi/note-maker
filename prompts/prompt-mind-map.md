

## Core Task (Reinforced)

Read and deeply understand the **entire** source text first.

Rebuild it as a **concise, concept-based, highly interconnected mind map** optimized for rapid review and exam use.

**The output must NOT be:**
- A rearranged or lightly edited version of the source order
- A long numbered list of topics (1., 2., 3. ... 14.)
- Scattered fragments of the same concept across multiple branches
- Paragraph-like long nodes

**Instead:**
1. Fully digest the whole content.
2. Identify the main overarching topic + **major conceptual clusters/entities**.
3. **Aggressively consolidate** every piece of information belonging to the same conceptual cluster — regardless of where it appeared in the source.
4. Merge duplicates and remove low-value repetition.
5. Reorganize strictly according to **conceptual logic, mechanisms, relationships, comparisons, and exam/high-yield value**.
6. Make logical connections explicit (cause → effect, structure → function, problem → compensation → consequence, A differs from B because...).

---

## Critical Improvement: Mandatory Concept Consolidation (Works for Any Topic)

This is the core upgrade. The previous version still allowed fragmentation in complex texts.

### Mandatory Pre-Processing Workflow (do this silently before writing OPML):

**Step 1: Identify Major Conceptual Clusters**
After reading the full text, ask:
- What are the big, relatively self-contained ideas, entities, processes, or themes that deserve their own top-level branch?
- These clusters should group related information that is currently scattered.

Examples depending on topic type:
- **Medical / Clinical topics** (e.g. your thyroid notes):
  - Diagnostic framework (TSH/FT4 logic)
  - Graves Disease (as ONE unified cluster)
  - Other thyrotoxicosis causes + uptake patterns
  - Primary Hypothyroidism
  - Congenital Hypothyroidism
  - Cross-cutting comparisons & distinctions
- **Historical / Event-based topics**: Major periods/events + their causes + short-term effects + long-term consequences + key actors
- **Biological / Pathway topics**: Key molecular/cellular processes + regulatory points + downstream effects + clinical or functional outcomes
- **Conceptual / Theoretical topics**: Core concept A + supporting mechanisms/arguments + counterpoints + broader implications/applications
- **Process or Mechanism-heavy topics**: Stepwise sequence + decision points + feedback loops + variations/exceptions + practical/exam relevance

**Step 2: Total Consolidation Rule (Non-Negotiable)**
- Once you decide a cluster deserves its own top-level branch (e.g. "Graves Disease" or "Photosynthesis Light Reactions" or "French Revolution - Causes"), **collect EVERY relevant piece of information** about it from the entire source and put it inside that single branch.
- Do **not** leave important sub-information in other numbered sections or scattered branches.
- If something overlaps multiple clusters, put the detailed version in the primary cluster and add concise distinctions or cross-references in a dedicated "Comparisons & Relationships" section.

**Step 3: Give Each Major Cluster a Logical Internal Structure**
Do **not** use a rigid template for all topics. Choose the internal organization that best fits the nature of that cluster.

Common useful patterns (adapt freely):

**Pattern A – For Clinical/Medical Entities (example)**
```
Graves Disease
├── Core Definition & Key Characteristics
├── Pathophysiology & Mechanism
├── Clinical Features (categorized logically)
├── Diagnosis (patterns + specific tests)
├── Treatment & Management
└── High-Yield Exam Points, Traps & Distinctions
```

**Pattern B – For Processes, Mechanisms or Pathways**
```
Light-Dependent Reactions (Photosynthesis)
├── Trigger / Starting Point
├── Main Steps (sequential with arrows)
├── Key Molecules & Energy Flow
├── Regulatory Mechanisms
├── Connection to Calvin Cycle / Overall Outcome
└── Exam-Relevant Details & Common Mistakes
```

**Pattern C – For Conceptual or Argument-Based Topics**
```
Core Concept: X
├── Precise Definition
├── Supporting Mechanisms / Evidence
├── Counterarguments or Limitations
├── Related Concepts & Interactions
├── Practical / Clinical / Real-World Implications
└── High-Yield Points for Exams / Analysis
```

**Pattern D – For Historical or Event Topics**
```
Major Event / Period
├── Background & Precipitating Causes
├── Key Developments / Turning Points (stepwise)
├── Short-term Effects
├── Long-term Consequences & Legacy
├── Important Comparisons (with similar events)
└── Exam High-Yield Angles
```

You can mix patterns or create hybrid structures when it makes conceptual sense. The goal is always **clarity + logical flow + easy navigation** in XMind.

---

## Exam / Review-Oriented Compression Rules

- Ruthlessly concise. The mind map should support fast review (ideally completable in 5–10 minutes).
- Nodes should be short phrases or single clear sentences (maximum 1–2 lines).
- Prioritize: mechanisms, cause-effect chains, diagnostic/clinical clues, comparisons, distinctions, common traps, mnemonics, must-know exceptions.
- Avoid: long explanations, repeated examples, low-yield facts, source-order preservation without conceptual reason.
- Use compact relationship language inside nodes:
  - `A → B because mechanism X`
  - `Graves vs Toxic MNG: diffuse high uptake vs patchy/focal`
  - `If TSH low + uptake low → think leak or exogenous (not true hyperfunction)`

---

## Accuracy & Terminology Rules

- Preserve scientific, historical, or domain accuracy.
- Keep standard terminology of the field.
- For bilingual sources (e.g. Persian medical notes), retain key English terms when they are high-yield for exams or international understanding.
- Do not add unsupported details.

---

## XMind Compatibility Rules

- Valid OPML 2.0
- Clean nested structure
- Short nodes for better visual layout
- Proper XML escaping
- Use 0–2 emojis per major section only for quick visual scanning (avoid overuse)

---

## Recommended High-Level Structure (Flexible)

Adapt this skeleton to your content. The key is having:
- Foundational / shared concepts near the top
- Major conceptual clusters as strong, consolidated top-level branches
- Dedicated space for comparisons, relationships, and overall exam strategy

```xml
<body>
  <outline text="Main Topic Title">

    <!-- Foundational / Shared Concepts (if applicable) -->
    <outline text="🧠 Foundational Framework / Core Logic">
      <!-- e.g. TSH feedback, diagnostic principles, basic definitions, etc. -->
    </outline>

    <!-- Major Conceptual Cluster 1 (fully consolidated) -->
    <outline text="Major Cluster/Entity 1 (e.g. Graves Disease or Photosynthesis Dark Reactions or French Revolution Causes)">
      <!-- Use the most suitable internal pattern from above -->
    </outline>

    <!-- Major Conceptual Cluster 2 -->
    <outline text="Major Cluster/Entity 2">
      <!-- ... -->
    </outline>

    <!-- Add more major clusters as needed -->

    <!-- Cross-cutting sections -->
    <outline text="🔄 Key Comparisons, Distinctions &amp; Pattern Recognition">
      <!-- Direct contrasts between clusters, e.g. high-uptake vs low-uptake, similar historical events, related pathways -->
    </outline>

    <outline text="🔗 Important Relationships &amp; Mechanisms">
      <!-- Cause-effect, feedback loops, interactions across clusters -->
    </outline>

    <outline text="⭐ Exam / Review High-Yield Strategy">
      <!-- Most testable points, classic clues, common traps, mnemonics, overall approach -->
    </outline>

    <outline text="🧩 Ultra-Short Final Review">
      <!-- 5–8 extremely condensed key takeaways for last-minute recall -->
    </outline>

  </outline>
</body>
```

---

## Final Validation Checklist (Mandatory before outputting OPML)

- [ ] Did I identify the major conceptual clusters first?
- [ ] Did I consolidate **all** information about each cluster into **one** dedicated top-level branch (no important fragments left elsewhere)?
- [ ] Did I avoid creating a long numbered list that follows source order?
- [ ] Is the internal structure of each major branch logical and helpful for that specific type of content?
- [ ] Are comparisons and logical connections explicit and easy to find?
- [ ] Is the overall map concise and suitable for rapid exam/review use?
- [ ] Would someone reviewing this in XMind quickly understand the big picture and key relationships?

If any item fails, go back and consolidate/reorganize.

---

## Output Requirements

- Produce a clean, valid `.opml` file.
- Use a descriptive filename (lowercase + underscores).
- After creating the file, respond **only** with the direct download link to the `.opml` file.
- Do not paste OPML code or add extra explanations in the final response when performing the mind-map task.
