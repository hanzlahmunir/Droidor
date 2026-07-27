# Day 3 · Experiment 7 — Agentic RAG vs Passive RAG

**Passive:** fixed single top-4 retrieval + inference prompt  
**Agentic:** LLM with a `search_book` tool it can call repeatedly, reformulating queries as needed  

## Tool-Use Summary

| Question | Agent tool calls | Queries the agent chose |
|---|---|---|
| How does Gatsby die? | 4 | "Gatsby death"; "Gatsby shot"; "Gatsby murdered"; "George Wilson shot Gatsby" |
| Compare how Gatsby and Tom each treat Da | 3 | "Gatsby and Tom treatment of Daisy"; "Gatsby Daisy relationship"; "Tom Daisy relationship" |
| Who is Nick Carraway and how does he kno | 2 | "Nick Carraway Gatsby relationship"; "Nick Carraway moves to Long Island" |

## Passive vs Agentic Answers

### How does Gatsby die?

**Agent tool calls (4):** ['Gatsby death', 'Gatsby shot', 'Gatsby murdered', 'George Wilson shot Gatsby']

**PASSIVE:**
> The provided context does not answer this question.

**AGENTIC:**
> Gatsby was shot and killed by George Wilson.

### Compare how Gatsby and Tom each treat Daisy.

**Agent tool calls (3):** ['Gatsby and Tom treatment of Daisy', 'Gatsby Daisy relationship', 'Tom Daisy relationship']

**PASSIVE:**
> Based on the provided context, it can be observed that Gatsby treats Daisy with a deep emotional investment and longing. He is insistent on speaking to her alone and is visibly affected by her words, as seen when "The words seemed to bite physically into Gatsby." He also claims that Daisy is leaving Tom for him, indicating that he believes they have a strong connection. Additionally, when they dance together, it is described as a "graceful, conservative foxtrot," suggesting a sense of intimacy and comfort between them.

In contrast, Tom's treatment of Daisy is more possessive and controlling. When Daisy admits that she is leaving him, Tom responds with disbelief and dismissal, saying "Nonsen

**AGENTIC:**
> Gatsby and Tom treat Daisy differently. Gatsby is deeply in love with Daisy and wants to be with her, while Tom is more possessive and controlling. Tom sees Daisy as a possession, something that belongs to him, and he is determined to keep her. Gatsby, on the other hand, wants Daisy to be happy and is willing to do whatever it takes to make her happy, even if it means giving her up. Tom is also more concerned with maintaining his social status and reputation, and he sees Daisy as a part of that. Gatsby, however, is more focused on his love for Daisy and is willing to risk everything to be with her. Overall, Gatsby's treatment of Daisy is more romantic and idealistic, while Tom's treatment is

### Who is Nick Carraway and how does he know Gatsby?

**Agent tool calls (2):** ['Nick Carraway Gatsby relationship', 'Nick Carraway moves to Long Island']

**PASSIVE:**
> Nick Carraway is the narrator of the story. He knows Gatsby as a neighbor, since Gatsby's house is located near his own in West Egg. The context does not provide detailed information about how they initially met or the extent of their relationship, but it is clear that Nick is familiar with Gatsby and is concerned about him when the lights in his house fail to go on one Saturday night, prompting Nick to visit and check on him.

**AGENTIC:**
> Nick Carraway is the narrator of 'The Great Gatsby'. He moves to Long Island's West Egg to work in the bond business. He rents a small house next to a grand mansion owned by Jay Gatsby, where he throws extravagant parties. Nick is a friend of Tom Buchanan, who is married to Daisy. Through his connections, Nick arranges a meeting between Gatsby and Daisy, which ultimately leads to a tragic confrontation with Tom.
