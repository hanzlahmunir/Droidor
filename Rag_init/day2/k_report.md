# Experiment 2 — k (Retrieved Chunks) vs Answer Quality

**Book:** The Great Gatsby  
**Embedding:** all-MiniLM-L6-v2 (fixed)  
**Chunk size:** 800, overlap=80 (fixed)  
**k values tested:** [2, 4, 8, 12]  

## Summary

| k | Avg Q Time | Avg Context Size | Avg Score | Q5 Answered? |
|---|---|---|---|---|
| 2 | 4.2s | 1315 chars | 12% | NO (refused) |
| 4 | 13.0s | 2563 chars | 32% | NO (refused) |
| 8 | 12.7s | 5244 chars | 36% | NO (refused) |
| 12 | 7.6s | 7853 chars | 36% | NO (refused) |

## Completeness Scores per Question

| Question | k=2 | k=4 | k=8 | k=12 |
|---|---|---|---|---|
| Who is Jay Gatsby and what is his dream? | REFUSED | REFUSED | REFUSED | REFUSED |
| What does the green light symbolize? | REFUSED | 100% | 100% | 100% |
| Describe the relationship between Gatsby and Daisy | 60% | 60% | 80% | 80% |
| Who is Nick Carraway and how does he know Gatsby? | REFUSED | REFUSED | REFUSED | REFUSED |
| How does Gatsby die? | REFUSED | REFUSED | REFUSED | REFUSED |

## Context Size vs Query Time Tradeoff

Larger k = more text fed to LLM = longer answers = slower.

| k | Q1 ctx | Q1 time | Q3 ctx | Q3 time | Q5 ctx | Q5 time |
|---|---|---|---|---|---|---|
| 2 | 1286c | 6.9s | 1135c | 5.4s | 1443c | 2.2s |
| 4 | 2479c | 4.6s | 2517c | 9.0s | 2804c | 3.1s |
| 8 | 5218c | 5.5s | 5150c | 8.6s | 5509c | 39.9s |
| 12 | 7650c | 10.7s | 7941c | 9.1s | 8190c | 3.9s |

## Q5 Deep Dive — "How does Gatsby die?"

### k=2

- Context size: 1443 chars
- Facts in context: 0/5
- Answer score: 0%
- Facts found: []
- Facts missing: ['wilson', 'shot', 'pool', 'myrtle', 'murder']
- Refused: True

> The provided context does not answer this question.

### k=4

- Context size: 2804 chars
- Facts in context: 0/5
- Answer score: 0%
- Facts found: []
- Facts missing: ['wilson', 'shot', 'pool', 'myrtle', 'murder']
- Refused: True

> The provided context does not answer this question.

### k=8

- Context size: 5509 chars
- Facts in context: 1/5
- Answer score: 0%
- Facts found: []
- Facts missing: ['wilson', 'shot', 'pool', 'myrtle', 'murder']
- Refused: True

> The provided context does not answer this question.

### k=12

- Context size: 8190 chars
- Facts in context: 1/5
- Answer score: 0%
- Facts found: []
- Facts missing: ['wilson', 'shot', 'pool', 'myrtle', 'murder']
- Refused: True

> The provided context does not answer this question.


## Full Answers per k

### Q1: Who is Jay Gatsby and what is his dream?

**k=2** — 6.9s — ctx=1286c — REFUSED

> The provided context does not answer this question.

**k=4** — 4.6s — ctx=2479c — REFUSED

> The provided context does not answer this question.

**k=8** — 5.5s — ctx=5218c — REFUSED

> The provided context does not answer this question.

**k=12** — 10.7s — ctx=7650c — REFUSED

> The provided context does not answer this question.

### Q2: What does the green light symbolize?

**k=2** — 2.9s — ctx=1233c — REFUSED

> The provided context does not answer this question.

**k=4** — 7.8s — ctx=2621c — 100% complete

> Based on the provided context, the green light represents "the orgiastic future that year by year
> recedes before us." It is located at the end of Daisy's dock and is associated with Gatsby's dream,
> which "must have seemed so close that he could hardly fail to grasp it."

**k=8** — 4.4s — ctx=5381c — 100% complete

> Based on the provided context, the green light symbolizes:  * **"the orgiastic future that year by
> year recedes before us."** * **Gatsby's dream**, which "must have seemed so close that he could
> hardly fail to grasp it." * **An "enchanted object" of colossal significance** that represented the
> great distance separating Gatsby from Daisy. Once they were reunited, this colossal significance
> vanished, and it became "again a green light on a dock."

**k=12** — 5.1s — ctx=7955c — 100% complete

> Based on the provided context, the green light symbolizes:  * **The "orgiastic future that year by
> year recedes before us"** which Gatsby believed in. * **Gatsby's dream**, which "must have seemed so
> close that he could hardly fail to grasp it." * **The colossal significance of the distance that
> separated Gatsby from Daisy.** When they were apart, it represented an "enchanted object" that
> seemed "as close as a star to the moon," but once they were reunited, that colossal significance
> vanished and it became "again a green light on a dock."

### Q3: Describe the relationship between Gatsby and Daisy.

**k=2** — 5.4s — ctx=1135c — 60% complete

> Based on the provided context, the relationship between Gatsby and Daisy is characterized by a deep,
> one-sided sense of commitment from Gatsby, which is complicated by Daisy's past and present ties to
> her husband, Tom:  * **Gatsby's Commitment:** Gatsby feels deeply committed to Daisy, as if he were
> "following of a grail." Even though she previously vanished into her rich life and left him with
> "nothing," he still feels "married to her."  * **The Conflict over Tom:** Gatsby is protective of
> Daisy and insists that she is leaving Tom. However, their relationship faces tension because Daisy
> admits she cannot truthfully say she never loved Tom, an admission that physically hurts Gatsby.
> Despite this pain, Daisy states with a visible effort that she is leaving her husband.

**k=4** — 9.0s — ctx=2517c — 60% complete

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

**k=8** — 8.6s — ctx=5150c — 80% complete

> Based on the provided context, the relationship between Gatsby and Daisy is characterized by the
> following details:  * **Their Past and Gatsby's Devotion:** Gatsby initially ended up in Daisy's
> house by "colossal accident" when he was a penniless young man. He "took Daisy one still October
> night," feeling he had "no real right to touch her hand." After she vanished into her wealthy life,
> leaving him with nothing, Gatsby felt "married to her" and committed himself to "the following of a
> grail."  * **Gatsby's Efforts to Reconnect:** Gatsby bought his mansion specifically to be "just
> across the bay" from Daisy. After waiting five years, he arranged a meeting with her by having the
> narrator invite her to tea without her knowing Gatsby would be there.  * **Their Reunion:** When
> they reunited at the narrator's house, they sat on a couch together; Daisy was crying, and Gatsby
> "literally glowed" with a radiating sense of well-being. Later, they danced a graceful foxtrot
> together and sat on the narrator's steps for half an hour.  * **Gatsby's Perception of Her:** Gatsby
> is deeply affected by Daisy, kissing her "curious and lovely mouth" while feeling breathless and
> "somehow, betrayed." He is overwhelmingly aware of her youth, her freshness, and how her wealth
> preserves her, viewing her as "gleaming like silver, safe and proud above the hot struggles of the
> poor." * **The Conflict Over Her Marriage:** Gatsby insists that Daisy does not love her husband,
> Tom, and demands that she tell Tom she never loved him. Gatsby panics and claims Daisy is leaving
> Tom. While Daisy agrees with a "visible effort" that she is leaving Tom, she tearfully admits to
> Gatsby that she cannot truthfully say she "never loved Tom."

**k=12** — 9.1s — ctx=7941c — 80% complete

> Based on the provided context, the relationship between Gatsby and Daisy is complex, deeply
> obsessive, and marked by a history of separation and high expectations:  * **A History of Longing
> and Inequality:** They met when Gatsby was a penniless young man in uniform who felt he had "no real
> right to touch her hand," though he eventually "took Daisy one still October night." He felt
> "married to her," but she vanished into her rich, full life, leaving him with nothing.  * **Gatsby's
> Colossal Illusion:** Gatsby committed himself to Daisy as if she were a "grail." He bought a mansion
> across the bay and waited five years just for the chance to be invited to tea to see her. He
> revalues all of his possessions based on her response to them. His illusion of her is so "colossal"
> that Daisy sometimes falls short of his idealized dreams of her. * **Reunion and Affection:** Upon
> reuniting, they share intimate moments—dancing, kissing, and sitting together. Daisy tells Gatsby
> that she loves him, and when they are together, Gatsby "literally glows" with a new well-being. *
> **Conflict Over Her Marriage:** Gatsby wants Daisy to tell her husband, Tom, that she never loved
> him so they can wipe the past out forever. However, this creates tension; while Daisy asserts with
> effort that she is leaving Tom, she admits to Gatsby that she cannot truthfully say she never loved
> Tom.

### Q4: Who is Nick Carraway and how does he know Gatsby?

**k=2** — 3.8s — ctx=1476c — REFUSED

> The provided context does not answer this question.

**k=4** — 40.3s — ctx=2394c — REFUSED

> The provided context does not answer this question.

**k=8** — 5.0s — ctx=4963c — REFUSED

> The provided context does not answer this question.

**k=12** — 9.0s — ctx=7528c — REFUSED

> The provided context does not answer this question.

### Q5: How does Gatsby die?

**k=2** — 2.2s — ctx=1443c — REFUSED

> The provided context does not answer this question.

**k=4** — 3.1s — ctx=2804c — REFUSED

> The provided context does not answer this question.

**k=8** — 39.9s — ctx=5509c — REFUSED

> The provided context does not answer this question.

**k=12** — 3.9s — ctx=8190c — REFUSED

> The provided context does not answer this question.
