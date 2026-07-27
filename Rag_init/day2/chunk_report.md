# Experiment 1 — Chunk Size vs Retrieval Precision

**Book:** The Great Gatsby  
**Embedding:** all-MiniLM-L6-v2 (fixed)  
**k (retrieved chunks):** 4 (fixed)  
**Configs tested:** 4  

## Summary

| Chunk Size | Overlap | # Chunks | Index Time | Avg Q Time | Avg Score | Q5 Answered? |
|---|---|---|---|---|---|---|
| 200 | 20 | 1990 | 15.9s | 3.6s | 8% | NO (refused) |
| 400 | 40 | 958 | 15.4s | 8.3s | 16% | NO (refused) |
| 800 | 80 | 447 | 12.5s | 9.3s | 32% | NO (refused) |
| 1600 | 160 | 197 | 7.6s | 10.1s | 32% | NO (refused) |

## Completeness Scores per Question

Score = % of expected answer keywords found in the LLM answer.

| Question | size=200 | size=400 | size=800 | size=1600 |
|---|---|---|---|---|
| Who is Jay Gatsby and what is his dream? | REFUSED | REFUSED | REFUSED | REFUSED |
| What does the green light symbolize? | 40% | 60% | 100% | 100% |
| Describe the relationship between Gatsby and Daisy | REFUSED | 20% | 60% | 60% |
| Who is Nick Carraway and how does he know Gatsby? | REFUSED | REFUSED | REFUSED | REFUSED |
| How does Gatsby die? | REFUSED | REFUSED | REFUSED | REFUSED |

## Retrieval Coverage

Did the retrieved chunks contain the expected keywords at all?

| Question | size=200 | size=400 | size=800 | size=1600 |
|---|---|---|---|---|
| Who is Jay Gatsby and what is his dream? | 0/6 facts | 4/6 facts | 5/6 facts | 3/6 facts |
| What does the green light symbolize? | 3/5 facts | 3/5 facts | 5/5 facts | 5/5 facts |
| Describe the relationship between Gatsby and Daisy | 1/5 facts | 2/5 facts | 3/5 facts | 3/5 facts |
| Who is Nick Carraway and how does he know Gatsby? | 1/5 facts | 0/5 facts | 1/5 facts | 1/5 facts |
| How does Gatsby die? | 0/5 facts | 0/5 facts | 0/5 facts | 0/5 facts |

## Q5 Deep Dive — "How does Gatsby die?"

This question failed across all models in Day 1. Tracking if chunk size fixes it.

### chunk_size=200, overlap=20

- Query time: 2.7s
- Context contained relevant facts: 0/5
- Answer score: 0%
- Keywords found: []
- Keywords missing: ['wilson', 'shot', 'pool', 'myrtle', 'murder']
- Refused to answer: True

> The provided context does not answer this question.

### chunk_size=400, overlap=40

- Query time: 2.5s
- Context contained relevant facts: 0/5
- Answer score: 0%
- Keywords found: []
- Keywords missing: ['wilson', 'shot', 'pool', 'myrtle', 'murder']
- Refused to answer: True

> The provided context does not answer this question.

### chunk_size=800, overlap=80

- Query time: 3.2s
- Context contained relevant facts: 0/5
- Answer score: 0%
- Keywords found: []
- Keywords missing: ['wilson', 'shot', 'pool', 'myrtle', 'murder']
- Refused to answer: True

> The provided context does not answer this question.

### chunk_size=1600, overlap=160

- Query time: 22.2s
- Context contained relevant facts: 0/5
- Answer score: 0%
- Keywords found: []
- Keywords missing: ['wilson', 'shot', 'pool', 'myrtle', 'murder']
- Refused to answer: True

> The provided context does not answer this question.


## Full Answers per Config

### Q1: Who is Jay Gatsby and what is his dream?

**chunk_size=200, overlap=20** — 4.0s — REFUSED

> The provided context does not answer this question.

**chunk_size=400, overlap=40** — 5.0s — REFUSED

> The provided context does not answer this question.

**chunk_size=800, overlap=80** — 5.3s — REFUSED

> The provided context does not answer this question.

**chunk_size=1600, overlap=160** — 6.9s — REFUSED

> The provided context does not answer this question.

### Q2: What does the green light symbolize?

**chunk_size=200, overlap=20** — 3.2s — 40% complete

> Based on the provided context, the green light symbolizes "the orgiastic future that year by year
> recedes before us."

**chunk_size=400, overlap=40** — 23.9s — 60% complete

> Based on the provided context, the green light represents "the orgiastic future that year by year
> recedes before us" which Gatsby believed in. It is also described as one of Gatsby's "enchanted
> objects" located at the end of a dock.

**chunk_size=800, overlap=80** — 7.9s — 100% complete

> Based on the provided context, the green light represents "the orgiastic future that year by year
> recedes before us." It is located at the end of Daisy's dock and is associated with Gatsby's dream,
> which "must have seemed so close that he could hardly fail to grasp it."

**chunk_size=1600, overlap=160** — 7.4s — 100% complete

> Based on the provided context, the green light at the end of Daisy's dock symbolizes:  * **Gatsby's
> dream**, which had seemed so close to him that "he could hardly fail to grasp it." * **"The
> orgiastic future that year by year recedes before us,"** which Gatsby believed in. * **An "enchanted
> object" of colossal significance** that represented the great distance separating Gatsby from Daisy,
> making her seem "very near to her, almost touching her."

### Q3: Describe the relationship between Gatsby and Daisy.

**chunk_size=200, overlap=20** — 5.1s — REFUSED

> The provided context does not answer this question.

**chunk_size=400, overlap=40** — 5.8s — 20% complete

> Based on the provided context, the relationship between Gatsby and Daisy is characterized by the
> following:  * **Mutual Affection:** Daisy has told Gatsby that she loves him, and she tells him that
> he resembles "the advertisement of the man." * **Frequent Visits:** Daisy visits Gatsby's house
> "quite often" in the afternoons.  * **Gatsby's Devotion and Sensitivity to Her Opinion:** Gatsby is
> highly protective of their privacy and deeply affected by Daisy's opinions. He fired all of his
> servants to prevent them from gossiping about her visits, and his entire lifestyle ("caravansary")
> fell apart because of "the disapproval in her eyes." * **Secret Arrangements:** Earlier in their
> relationship, Gatsby wanted to arrange a meeting with Daisy by having Nick invite her to tea,
> specifically requesting that she not know Gatsby would be there.

**chunk_size=800, overlap=80** — 6.1s — 60% complete

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

**chunk_size=1600, overlap=160** — 7.0s — 60% complete

> Based on the provided context, the relationship between Gatsby and Daisy is characterized by the
> following details:  * **The Past and Origins:** Gatsby initially took Daisy under false pretenses,
> letting her believe he was from the same social strata as her and fully able to take care of her,
> though he actually had no comfortable family standing. Although he originally intended to "take what
> he could and go," he found himself deeply committed to her, feeling "married to her" and as if he
> were "following of a grail." When they met again two days later, they kissed, and Gatsby was
> overwhelmingly aware of her youth, mystery, and how her wealth kept her "safe and proud above the
> hot struggles of the poor." * **Present Interactions:** At a party, Gatsby and Daisy dance together
> (a graceful, conservative foxtrot) and spend a half-hour sitting alone on Nick's porch while Nick
> stands watch. This half-hour is the only time Daisy enjoys herself during the party.  * **Gatsby's
> Defense of Her:** Gatsby strongly believes that Daisy never loved her husband, Tom. He defends her
> actions to Nick, claiming she was highly excited and frightened by Tom making Gatsby look like a
> "cheap sharper," which caused her to hardly know what she was saying.

### Q4: Who is Nick Carraway and how does he know Gatsby?

**chunk_size=200, overlap=20** — 3.0s — REFUSED

> The provided context does not answer this question.

**chunk_size=400, overlap=40** — 4.3s — REFUSED

> The provided context does not answer this question.

**chunk_size=800, overlap=80** — 23.8s — REFUSED

> The provided context does not answer this question.

**chunk_size=1600, overlap=160** — 7.1s — REFUSED

> The provided context does not answer this question.

### Q5: How does Gatsby die?

**chunk_size=200, overlap=20** — 2.7s — REFUSED

> The provided context does not answer this question.

**chunk_size=400, overlap=40** — 2.5s — REFUSED

> The provided context does not answer this question.

**chunk_size=800, overlap=80** — 3.2s — REFUSED

> The provided context does not answer this question.

**chunk_size=1600, overlap=160** — 22.2s — REFUSED

> The provided context does not answer this question.
