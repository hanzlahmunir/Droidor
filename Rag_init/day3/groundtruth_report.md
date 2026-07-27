# Day 3 · Experiment 5 — Ground-Truth Answer Evaluation

Objective correctness vs known-true answers, graded by an LLM judge (CORRECT / PARTIAL / WRONG / REFUSED), across 3 system designs.

| Question | Passive-Strict | Passive-Inference |
|---|---|---|
| How does Gatsby die? | REFUSED | REFUSED |
| What does the green light symbolize? | CORRECT | CORRECT |
| Who is Nick Carraway and how does he kno | PARTIAL | PARTIAL |
| Who killed Myrtle Wilson? | WRONG | WRONG |

**Weighted accuracy (CORRECT=1, PARTIAL=0.5):**  
- Passive-Strict: 1.5/4  
- Passive-Inference: 1.5/4  

## Full Answers

### How does Gatsby die?

**Ground truth:** Gatsby is shot dead in his swimming pool by George Wilson, who then kills himself. Wilson wrongly believed Gatsby was driving the car that killed his wife Myrtle (Daisy was actually driving).

**Passive-Strict (REFUSED):** The provided context does not answer this question.

**Passive-Inference (REFUSED):** The provided context does not answer this question.

### What does the green light symbolize?

**Ground truth:** The green light at the end of Daisy's dock symbolizes Gatsby's hopes and dreams for the future — specifically his longing for Daisy — and more broadly the elusive American Dream.

**Passive-Strict (CORRECT):** The green light symbolizes the "orgiastic future" that Gatsby believes in, representing the elusive and often unattainable goal that he strives for, which is likely related to winning back Daisy. It is described as something that "year by year recedes before us", indicating that it is always just ou

**Passive-Inference (CORRECT):** The green light symbolizes the elusive and often unattainable American Dream, which Gatsby longs for. It represents the idea of a perfect and idealized future, which is always receding and seems within reach but is ultimately unattainable. The green light is specifically associated with Daisy, who e

### Who is Nick Carraway and how does he know Gatsby?

**Ground truth:** Nick Carraway is the narrator, a young bond salesman who moves to West Egg. He is Gatsby's next-door neighbor and also Daisy's cousin, which is how he becomes the link between Gatsby and Daisy.

**Passive-Strict (PARTIAL):** The provided context does not fully answer this question. However, it can be inferred that Nick Carraway is the narrator of the story, and he knows Gatsby as a neighbor, since he goes over to Gatsby's house to check on him when the lights in Gatsby's house fail to go on one Saturday night. He also s

**Passive-Inference (PARTIAL):** Nick Carraway is the narrator of the story. He knows Gatsby as a neighbor, since Gatsby's house is located near his own in West Egg. The context does not provide detailed information about how they initially met, but it is mentioned that Nick went over to Gatsby's house to find out if he was sick wh

### Who killed Myrtle Wilson?

**Ground truth:** Myrtle Wilson is struck and killed by Gatsby's car, which Daisy was driving (though Gatsby takes the blame).

**Passive-Strict (WRONG):** The provided context does not directly answer this question, but it implies that Tom was involved in Myrtle's death, as he mentions "He ran over Myrtle like you’d run over a dog and never even stopped his car." However, it is not explicitly stated that Tom was the one driving the car.

**Passive-Inference (WRONG):** The provided context does not answer this question directly, but it implies that Tom Buchanan was involved in Myrtle Wilson's death, as he mentions that the person who killed her "ran over Myrtle like you'd run over a dog and never even stopped his car" and that he had told Wilson who owned the car,

## Takeaway

- This is the objective accuracy metric missing from Days 1-2, confirming the strict->inference progression: the strict prompt refuses answerable questions, the inference prompt answers what's retrievable. (The agent column was dropped — see note in source; its correctness advantage is shown in Experiment 7.)
- Where BOTH prompts fail (e.g. Gatsby's death), it's a RETRIEVAL failure per Exp 6 — the chunk isn't retrieved, so no prompt helps. Only the agent's query reformulation (Exp 7) fixes those.