# Experiment 3 — Hybrid Search (Semantic + BM25)

**Book:** The Great Gatsby  
**Embedding:** all-MiniLM-L6-v2 (fixed)  
**Chunk size:** 800, overlap=80 (fixed)  
**k:** 4 per retriever  

## Summary

| Strategy | Avg Q Time | Avg Score | Q5 Answered? |
|---|---|---|---|
| Semantic only (FAISS) | 5.3s | 32% | NO (refused) |
| BM25 keyword only | 4.3s | 24% | NO (refused) |
| Hybrid 50% semantic + 50% BM25 | 8.0s | 28% | NO (refused) |
| Hybrid 30% semantic + 70% BM25 | 8.1s | 36% | NO (refused) |

## Completeness Scores per Question

| Question | Semantic only (FAISS) | BM25 keyword only | Hybrid 50% semantic + 50% BM25 | Hybrid 30% semantic + 70% BM25 |
|---|---|---|---|---|
| Who is Jay Gatsby and what is his dream? | REFUSED | REFUSED | REFUSED | REFUSED |
| What does the green light symbolize? | 100% | 80% | 80% | 100% |
| Describe the relationship between Gatsby and Daisy | 60% | 40% | 60% | 80% |
| Who is Nick Carraway and how does he know Gatsby? | REFUSED | REFUSED | REFUSED | REFUSED |
| How does Gatsby die? | REFUSED | REFUSED | REFUSED | REFUSED |

## Q5 Deep Dive — "How does Gatsby die?"

The question that failed across all chunk sizes and k values.

### Semantic only (FAISS)

- Facts in retrieved context: 0/5
- Answer score: 0%  |  Refused: True
- Facts found: []
- Facts missing: ['wilson', 'shot', 'pool', 'myrtle', 'murder']

**Retrieved chunk previews:**
  - Chunk 1: `A dim background started to take shape behind him, but at her next remark it faded away.  “However, I don’t believe it.”...`
  - Chunk 2: `It was Gatsby’s father, a solemn old man, very helpless and dismayed, bundled up in a long cheap ulster against the warm...`
  - Chunk 3: `heightened sensitivity to the promises of life, as if he were related to one of those intricate machines that register e...`
  - Chunk 4: `“I don’t think so,” she said innocently. “Why?”  We went in. To my overwhelming surprise the living-room was deserted.  ...`

**Answer:**
> The provided context does not answer this question.

### BM25 keyword only

- Facts in retrieved context: 1/5
- Answer score: 0%  |  Refused: True
- Facts found: []
- Facts missing: ['wilson', 'shot', 'pool', 'myrtle', 'murder']

**Retrieved chunk previews:**
  - Chunk 1: `I disliked him so much by this time that I didn’t find it necessary to tell him he was wrong.  “Who was the woman?” he i...`
  - Chunk 2: `Almost at the moment when Mr. Gatsby identified himself a butler hurried toward him with the information that Chicago wa...`
  - Chunk 3: `“Terrible place, isn’t it,” said Tom, exchanging a frown with Doctor Eckleburg.  “Awful.”  “It does her good to get away...`
  - Chunk 4: `We walked through a high hallway into a bright rosy-coloured space, fragilely bound into the house by French windows at ...`

**Answer:**
> The provided context does not answer this question.

### Hybrid 50% semantic + 50% BM25

- Facts in retrieved context: 1/5
- Answer score: 0%  |  Refused: True
- Facts found: []
- Facts missing: ['wilson', 'shot', 'pool', 'myrtle', 'murder']

**Retrieved chunk previews:**
  - Chunk 1: `A dim background started to take shape behind him, but at her next remark it faded away.  “However, I don’t believe it.”...`
  - Chunk 2: `I disliked him so much by this time that I didn’t find it necessary to tell him he was wrong.  “Who was the woman?” he i...`
  - Chunk 3: `It was Gatsby’s father, a solemn old man, very helpless and dismayed, bundled up in a long cheap ulster against the warm...`
  - Chunk 4: `Almost at the moment when Mr. Gatsby identified himself a butler hurried toward him with the information that Chicago wa...`
  - Chunk 5: `heightened sensitivity to the promises of life, as if he were related to one of those intricate machines that register e...`
  - Chunk 6: `“Terrible place, isn’t it,” said Tom, exchanging a frown with Doctor Eckleburg.  “Awful.”  “It does her good to get away...`
  - Chunk 7: `“I don’t think so,” she said innocently. “Why?”  We went in. To my overwhelming surprise the living-room was deserted.  ...`
  - Chunk 8: `We walked through a high hallway into a bright rosy-coloured space, fragilely bound into the house by French windows at ...`

**Answer:**
> The provided context does not answer this question.

### Hybrid 30% semantic + 70% BM25

- Facts in retrieved context: 1/5
- Answer score: 0%  |  Refused: True
- Facts found: []
- Facts missing: ['wilson', 'shot', 'pool', 'myrtle', 'murder']

**Retrieved chunk previews:**
  - Chunk 1: `I disliked him so much by this time that I didn’t find it necessary to tell him he was wrong.  “Who was the woman?” he i...`
  - Chunk 2: `Almost at the moment when Mr. Gatsby identified himself a butler hurried toward him with the information that Chicago wa...`
  - Chunk 3: `“Terrible place, isn’t it,” said Tom, exchanging a frown with Doctor Eckleburg.  “Awful.”  “It does her good to get away...`
  - Chunk 4: `We walked through a high hallway into a bright rosy-coloured space, fragilely bound into the house by French windows at ...`
  - Chunk 5: `A dim background started to take shape behind him, but at her next remark it faded away.  “However, I don’t believe it.”...`
  - Chunk 6: `It was Gatsby’s father, a solemn old man, very helpless and dismayed, bundled up in a long cheap ulster against the warm...`
  - Chunk 7: `heightened sensitivity to the promises of life, as if he were related to one of those intricate machines that register e...`
  - Chunk 8: `“I don’t think so,” she said innocently. “Why?”  We went in. To my overwhelming surprise the living-room was deserted.  ...`

**Answer:**
> The provided context does not answer this question.


## Full Answers per Strategy

### Q1: Who is Jay Gatsby and what is his dream?

**Semantic only (FAISS)** — 5.0s — REFUSED

> The provided context does not answer this question.

**BM25 keyword only** — 4.8s — REFUSED

> The provided context does not answer this question.

**Hybrid 50% semantic + 50% BM25** — 4.2s — REFUSED

> The provided context does not answer this question.

**Hybrid 30% semantic + 70% BM25** — 23.2s — REFUSED

> The provided context does not answer this question.

### Q2: What does the green light symbolize?

**Semantic only (FAISS)** — 8.3s — 100% complete

> Based on the provided context, the green light represents "the orgiastic future that year by year
> recedes before us." It is located at the end of Daisy's dock and is associated with Gatsby's dream,
> which "must have seemed so close that he could hardly fail to grasp it."

**BM25 keyword only** — 3.6s — 80% complete

> Based on the provided context, the green light symbolizes:  * **Gatsby's dream**, which "must have
> seemed so close that he could hardly fail to grasp it." * **The "orgiastic future** that year by
> year recedes before us." * **An "enchanted object" of "colossal significance"** that represented the
> great distance separating Gatsby from Daisy (seeming "as close as a star to the moon" and "almost
> touching her" when they were apart).

**Hybrid 50% semantic + 50% BM25** — 3.5s — 80% complete

> Based on the provided context, the green light symbolizes:  * **Gatsby's dream**, which "must have
> seemed so close that he could hardly fail to grasp it." * **"The orgiastic future that year by year
> recedes before us,"** which Gatsby believed in.  * **An "enchanted object" of "colossal
> significance"** that represented the great distance that had separated Gatsby from Daisy.

**Hybrid 30% semantic + 70% BM25** — 3.5s — 100% complete

> Based on the provided context, the green light (which is located at the end of Daisy's dock)
> symbolizes:  * **Gatsby's dream:** A dream that "must have seemed so close that he could hardly fail
> to grasp it." * **The future:** Specifically, "the orgiastic future that year by year recedes before
> us." * **Gatsby's yearning and proximity to Daisy:** It was one of his "enchanted objects" of
> "colossal significance" that represented the great distance separating him from Daisy, making his
> dream of her seem "very near to her, almost touching her" and "as close as a star to the moon."

### Q3: Describe the relationship between Gatsby and Daisy.

**Semantic only (FAISS)** — 6.4s — 60% complete

> Based on the provided context, the relationship between Gatsby and Daisy is characterized by the
> following:  * **Deep Commitment and Obsession:** Gatsby feels deeply committed to Daisy, viewing her
> as "extraordinary" and feeling "married to her" as if he were "following of a grail," even though
> she previously vanished into her rich life and left him with nothing.  * **Secret Meetings and
> Connection:** Gatsby desires to see Daisy and arranges to have her invited to tea without her
> knowing he will be there. They also share intimate moments, such as dancing a graceful foxtrot
> together and sitting on the narrator's steps for half an hour. * **Conflict Over Her Husband:**
> Gatsby insists that Daisy is leaving her husband, Tom, which Daisy confirms with a visible effort.
> However, Daisy admits she cannot truthfully say she "never loved Tom," a statement that physically
> hurts Gatsby.

**BM25 keyword only** — 8.8s — 40% complete

> Based on the provided context, the relationship between Gatsby and Daisy is characterized by the
> following details:  * **A tense conflict involving Daisy's husband:** Tom accuses Gatsby of "making
> love" to Daisy. During a confrontation, Daisy defends Gatsby, telling Tom that he is the one
> "causing a row," and she stares "terrified" between the two men.  * **Gatsby's disbelief of her
> family life:** Gatsby is surprised by the physical presence of Daisy's child, as he had never
> "really believed in its existence before." * **A lack of contact during a crisis:** Following an
> event that draws police and journalists, the narrator expects Daisy to send a wire, but she fails to
> do so.

**Hybrid 50% semantic + 50% BM25** — 6.1s — 60% complete

> Based on the provided context, the relationship between Gatsby and Daisy is characterized by the
> following:  * **Gatsby's Devotion:** Gatsby felt "married to" Daisy and committed himself to her as
> if "following of a grail." He viewed her as "extraordinary," though she initially vanished into her
> rich house and life, leaving him with nothing.  * **Secret Meetings and Connection:** Gatsby wanted
> to see Daisy and had Jordan ask the narrator to invite her to tea without her knowing Gatsby was
> behind it. Later, they danced together and spent time sitting on the narrator's steps. * **The
> Conflict Over Her Husband:** Gatsby insisted that Daisy was leaving her husband, Tom, and that Tom
> would no longer take care of her. While Daisy stated with a visible effort that she was leaving Tom,
> she also admitted to Gatsby's panic that she could not say she "never loved Tom." * **The Child:**
> Gatsby struggled to believe in the actual existence of Daisy's child until he met her in person.

**Hybrid 30% semantic + 70% BM25** — 6.6s — 80% complete

> Based on the provided context, the relationship between Gatsby and Daisy is a complex, romantic, and
> tense connection characterized by the following details:  * **Deep Commitment:** Gatsby is deeply
> committed to Daisy, viewing her as "extraordinary" and feeling as though he has "committed himself
> to the following of a grail." Even though she had previously vanished into her rich life and left
> him with "nothing," he still "felt married to her." * **An Affair and Secret Meetings:** Tom accuses
> Gatsby of being a "Mr. Nobody" who is making love to his wife. Gatsby and Daisy dance together,
> spend time alone sitting on Nick's steps, and Gatsby secretly arranges to meet her by having Nick
> invite her to tea without her prior knowledge.  * **Denial of her Past:** Gatsby struggles to accept
> Daisy's life separate from him. He looks at her child with surprise, having never truly believed the
> child existed.  * **Conflict Over her Marriage:** Gatsby panics when Daisy admits she cannot
> truthfully say she "never loved Tom." Despite this, Gatsby insists to Tom that Daisy is leaving him
> and that Tom will no longer take care of her—a claim Daisy supports "with a visible effort," saying,
> "I am, though."

### Q4: Who is Nick Carraway and how does he know Gatsby?

**Semantic only (FAISS)** — 4.3s — REFUSED

> The provided context does not answer this question.

**BM25 keyword only** — 2.4s — REFUSED

> The provided context does not answer this question.

**Hybrid 50% semantic + 50% BM25** — 4.2s — REFUSED

> The provided context does not answer this question.

**Hybrid 30% semantic + 70% BM25** — 3.7s — REFUSED

> The provided context does not answer this question.

### Q5: How does Gatsby die?

**Semantic only (FAISS)** — 2.4s — REFUSED

> The provided context does not answer this question.

**BM25 keyword only** — 1.9s — REFUSED

> The provided context does not answer this question.

**Hybrid 50% semantic + 50% BM25** — 22.0s — REFUSED

> The provided context does not answer this question.

**Hybrid 30% semantic + 70% BM25** — 3.3s — REFUSED

> The provided context does not answer this question.
