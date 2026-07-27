# Q5 Fix — Parent-Document Retriever + Inference Prompt

**Child chunks:** 200c (matching)  |  **Parent chunks:** 2000c (fed to LLM)  
**Embedding:** all-MiniLM-L6-v2  |  **Prompt:** inference-allowed  

## Results

| Question | Answered? | Death-scene signals in retrieved context |
|---|---|---|
| Who is Jay Gatsby and what is his dream? | ANSWERED | — |
| What does the green light symbolize? | ANSWERED | pool |
| Describe the relationship between Gatsby and  | ANSWERED | — |
| Who is Nick Carraway and how does he know Gat | REFUSED | wilson |
| How does Gatsby die? | REFUSED | — |

## Q5 Deep Dive — did the death scene finally get retrieved?

- Death-scene signals now in context: **[]**
- Context size fed to LLM: 5294 chars
- Answered: **False**

**Retrieved context preview:**
> “Who’s this?”

“That? That’s Mr. Dan Cody, old sport.”

The name sounded faintly familiar.

“He’s dead now. He used to be my best friend years ago.”

There was a small picture of Gatsby, also in yachting costume, on the
bureau—Gatsby with his head thrown back defiantly—taken apparently
when he was a...


**Answer:**
> The provided context does not answer this question.


## All Answers

### Who is Jay Gatsby and what is his dream?

- Answered: True  |  signals: []

> Based on the provided context, here is who Jay Gatsby is and what his dream is:

### **Who is Jay Gatsby?**
* **His Origins:** He was legally born **James Gatz**, the son of "shiftless and unsuccessful farm people" whom he never truly accepted as his parents. 
* **His Self-Creation:** At age seventeen, while working as a clam-digger and salmon-fisher on Lake Superior, he changed his name to **Jay Gatsby**. This new identity sprang from his "Platonic conception of himself" as a "son of God."
* **His Mentorship with Dan Cody:** He spent five years working in a vague personal capacity (as a stewa

### What does the green light symbolize?

- Answered: True  |  signals: ['pool']

> Based on the provided context, the green light symbolizes:

* **Gatsby's dream of being with Daisy:** Located at the end of Daisy's dock, the light represents the immense distance that separated Gatsby from her. To Gatsby, it was an "enchanted object" that made his dream of reaching her seem incredibly close—"almost touching her" and "as close as a star to the moon."
* **An elusive, unreachable future:** It symbolizes "the orgiastic future that year by year recedes before us." It represents the human pursuit of a dream that seems so close we "could hardly fail to grasp it," yet remains just ou

### Describe the relationship between Gatsby and Daisy.

- Answered: True  |  signals: []

> Based on the provided context, the relationship between Gatsby and Daisy is highly intense, complicated, and strained by Gatsby's extreme expectations and their shared past:

*   **Gatsby’s Obsession and High Expectations:** Gatsby is deeply devoted to Daisy. He has spent years reading a Chicago newspaper just on the chance of seeing her name, and he orchestrates a secret meeting (an invitation to tea) just to see her. However, Gatsby demands absolute devotion; he insists that Daisy tell her husband, Tom, that she never loved him, believing this will completely erase the past. 
*   **Daisy’s C

### Who is Nick Carraway and how does he know Gatsby?

- Answered: False  |  signals: ['wilson']

> The provided context does not answer this question.

### How does Gatsby die?

- Answered: False  |  signals: []

> The provided context does not answer this question.
