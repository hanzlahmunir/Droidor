# Prompt Comparison — Strict vs Inference Guardrail

**Retrieval (identical for both):** all-MiniLM-L6-v2, chunk=800, k=4, semantic FAISS  
**Only variable:** the generation prompt's grounding instruction  

## Score Comparison

| Question | STRICT | INFERENCE | Change |
|---|---|---|---|
| Who is Jay Gatsby and what is his dream? | REFUSED | 83% | ✅ REFUSED → ANSWERED |
| What does the green light symbolize? | 100% | 100% | +0% |
| Describe the relationship between Gatsby and Dai | 60% | 60% | +0% |
| Who is Nick Carraway and how does he know Gatsby | REFUSED | 20% | ✅ REFUSED → ANSWERED |
| How does Gatsby die? | REFUSED | REFUSED | still refused |

**Refusals:** STRICT 3/5 → INFERENCE 1/5  
**Avg score (counting refusals as 0):** STRICT 32% → INFERENCE 53%  

## Full Answers

### Who is Jay Gatsby and what is his dream?

**STRICT (REFUSED):**
> The provided context does not answer this question.

**INFERENCE (83%):**
> Based on the provided context, here is who Jay Gatsby is and what can be inferred about his dream:

**Who is Jay Gatsby?**
* **A Self-Created Persona:** Originally the son of "shiftless and unsuccessful farm people" whom he never truly accepted as his parents, he rejected his past at age seventeen to invent the identity of "Jay Gatsby of West Egg, Long Island." 
* **A "Son of God":** He sprang from his own "Platonic conception of himself" and dedicated himself to the "service of a vast, vulgar, and meretricious beauty."
* **A Man of Hope:** He possesses an "extraordinary gift for hope" and a "

### What does the green light symbolize?

**STRICT (100%):**
> Based on the provided context, the green light represents "the orgiastic future that year by year recedes before us." It is located at the end of Daisy's dock and is associated with Gatsby's dream, which "must have seemed so close that he could hardly fail to grasp it."

**INFERENCE (100%):**
> Based on the provided context, the green light at the end of Daisy’s dock symbolizes:

1. **Gatsby's dream:** It represents a dream that seemed so close to Gatsby that he felt he "could hardly fail to grasp it," even though he did not realize it was already behind him. 
2. **The "orgiastic future" and human hope:** It symbolizes the elusive future and the hopes we strive for year after year. It represents the human determination to keep reaching for our dreams, believing that "tomorrow we will run faster, stretch out our arms further," even as we are "borne back ceaselessly into the past."

### Describe the relationship between Gatsby and Daisy.

**STRICT (60%):**
> Based on the provided context, the relationship between Gatsby and Daisy is characterized by the following:

* **Deep Commitment and Obsession:** Gatsby feels deeply committed to Daisy, viewing her as "extraordinary" and feeling "married to her" as if he were "following of a grail," even though she previously vanished into her rich life and left him with nothing. 
* **Secret Meetings and Connection:** Gatsby desires to see Daisy and arranges to have her invited to tea without her knowing he will be there. They also share intimate moments, such as dancing a graceful foxtrot together and sitting

**INFERENCE (60%):**
> Based on the provided context, the relationship between Gatsby and Daisy is an intense, complicated, and secretive romance marked by deep devotion, high expectations, and underlying tension:

* **Gatsby’s Intense Devotion:** Gatsby is deeply, almost obsessively committed to Daisy. He views her as an extraordinary "grail" that he is bound to follow, and he feels "married to her" even though she previously vanished into her wealthy, separate life and left him with nothing. He orchestrates secret ways to see her, such as arranging a tea invitation through the narrator without her prior knowledge.

### Who is Nick Carraway and how does he know Gatsby?

**STRICT (REFUSED):**
> The provided context does not answer this question.

**INFERENCE (20%):**
> The provided context does not answer this question. It only refers to the narrator as "Mr. Carraway" (never mentioning the first name "Nick") and does not explain how he and Gatsby first met or how they know each other, other than showing that they have met and that Carraway visited Gatsby's house when he was worried Gatsby might be sick.

### How does Gatsby die?

**STRICT (REFUSED):**
> The provided context does not answer this question.

**INFERENCE (REFUSED):**
> The provided context does not answer this question.
