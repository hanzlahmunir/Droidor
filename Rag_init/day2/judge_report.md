# Experiment 4 — LLM-as-Judge vs Keyword Scorer

**Answers graded:** inference-prompt config (all-MiniLM-L6-v2, chunk=800, k=4, semantic)  
**Judge:** gemini-flash-latest, scoring Faithfulness & Completeness (1-5)  

## Keyword Score vs Judge Verdict

| Question | Keyword | Faithfulness | Completeness | Judge's reason |
|---|---|---|---|---|
| Who is Jay Gatsby and what is his dream? | 83% | 5/5 | 5/5 | The answer is highly faithful to the context, accurately extracting details abou |
| What does the green light symbolize? | 100% | 5/5 | 5/5 | The answer is fully faithful to the context and completely captures the symbolic |
| Describe the relationship between Gatsby | 60% | 5/5 | 5/5 | The answer is fully faithful to the context, accurately capturing all details ab |
| Who is Nick Carraway and how does he kno | 20% | 5/5 | 3/5 | The context does not contain information about who Nick Carraway is or how he kn |
| How does Gatsby die? | REFUSED | 5/5 | 3/5 | The provided context does not contain information explaining how Gatsby dies, so |

## Where Keyword Scoring and the Judge Disagree

- **How does Gatsby die?** (kw=REFUSED, F=5, C=3): Judge says the refusal was appropriate (context lacked the answer).

## Full Answers + Judge Reasoning

### Who is Jay Gatsby and what is his dream?

- Keyword score: **83%**
- Judge: **Faithfulness 5/5, Completeness 5/5**
- Judge reason: The answer is highly faithful to the context, accurately extracting details about Gatsby's identity and dreams, and fully addresses the prompt using only the provided text.

> Based on the provided context, here is who Jay Gatsby is and what can be inferred about his dream:

**Who is Jay Gatsby?**
* **A Self-Created Persona:** Originally the son of "shiftless and unsuccessful farm people" whom he never truly accepted as his parents, he rejected his past at age seventeen to invent the identity of "Jay Gatsby of West Egg, Long Island." 
* **A "Son of God":** He sprang from his own "Platonic conception of himself" and dedicated himself to the "service of a vast, vulgar, and meretricious beauty."
* **A Man of Hope:** He possesses an "extraordinary gift for hope" and a "romantic readiness" and "heightened sensitivity to the promises of life" unmatched by anyone else.
*

### What does the green light symbolize?

- Keyword score: **100%**
- Judge: **Faithfulness 5/5, Completeness 5/5**
- Judge reason: The answer is fully faithful to the context and completely captures the symbolic meanings of the green light as described in the text.

> Based on the provided context, the green light at the end of Daisy’s dock symbolizes:

1. **Gatsby's dream:** It represents a dream that seemed so close to Gatsby that he felt he "could hardly fail to grasp it," even though he did not realize it was already behind him. 
2. **The "orgiastic future" and human hope:** It symbolizes the elusive future and the hopes we strive for year after year. It represents the human determination to keep reaching for our dreams, believing that "tomorrow we will run faster, stretch out our arms further," even as we are "borne back ceaselessly into the past."

### Describe the relationship between Gatsby and Daisy.

- Keyword score: **60%**
- Judge: **Faithfulness 5/5, Completeness 5/5**
- Judge reason: The answer is fully faithful to the context, accurately capturing all details about Gatsby and Daisy's relationship, and completely addresses the prompt.

> Based on the provided context, the relationship between Gatsby and Daisy is an intense, complicated, and secretive romance marked by deep devotion, high expectations, and underlying tension:

* **Gatsby’s Intense Devotion:** Gatsby is deeply, almost obsessively committed to Daisy. He views her as an extraordinary "grail" that he is bound to follow, and he feels "married to her" even though she previously vanished into her wealthy, separate life and left him with nothing. He orchestrates secret ways to see her, such as arranging a tea invitation through the narrator without her prior knowledge.
* **Secret Intimacy:** They share a romantic connection, illustrated by them dancing together and s

### Who is Nick Carraway and how does he know Gatsby?

- Keyword score: **20%**
- Judge: **Faithfulness 5/5, Completeness 3/5**
- Judge reason: The context does not contain information about who Nick Carraway is or how he knows Gatsby, so the system correctly refused to answer while accurately summarizing what little is known from the text.

> The provided context does not answer this question. It only refers to the narrator as "Mr. Carraway" (never mentioning the first name "Nick") and does not explain how he and Gatsby first met or how they know each other, other than showing that they have met and that Carraway visited Gatsby's house when he was worried Gatsby might be sick.

### How does Gatsby die?

- Keyword score: **REFUSED**
- Judge: **Faithfulness 5/5, Completeness 3/5**
- Judge reason: The provided context does not contain information explaining how Gatsby dies, so the system correctly refused to answer.

> The provided context does not answer this question.
