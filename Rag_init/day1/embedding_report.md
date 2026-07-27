# Embedding Model Evaluation — The Great Gatsby

**Book:** The Great Gatsby by F. Scott Fitzgerald  
**Chunks:** 452 (800 chars, 100 overlap)  
**Questions:** 5  

## Summary

| Model | Index Time | Avg Query Time | Hallucinations |
|---|---|---|---|
| all-MiniLM-L6-v2 (local, 384-dim, fast) | 14.2s | 22.71s | 5/5 |
| all-mpnet-base-v2 (local, 768-dim, balanced) | 99.4s | 71.73s | 5/5 |
| nomic-embed-text-v1 (local, 768-dim, high quality) | 120.8s | 5.75s | 5/5 |

## Answers per Model

### Q1: Who is Jay Gatsby and what is his dream?

**all-MiniLM-L6-v2 (local, 384-dim, fast)** — 50.80s — 🔴 SUSPECT (terms not in context: Jordan Baker, Based)

> Based on the provided context:  **Who is Jay Gatsby?** * Jay Gatsby of West Egg, Long Island, is a
> man who "sprang from his Platonic conception of himself," having invented his identity when he was
> seventeen years old.  * He is the son of "shiftless and unsuccessful farm people," though his
> imagination never accepted them as his parents; instead, he saw himself as a "son of God." * He is
> described as having an "extraordinary gift for hope" and a "romantic readiness."  * He was once a
> "penniless young man without a past" who wore a military uniform, and he once told Jordan Baker that
> he was an "Oxford man."  **What is his dream?** * The context does not fully define a single
> specific dream, but it states that his life's purpose and conception of himself was to be "about His
> Father’s business, the service of a vast, vulgar, and meretricious beauty." He remained faithful to
> this self-invented conception to the end, though "foul dust floated in the wake of his dreams."

**all-mpnet-base-v2 (local, 768-dim, balanced)** — 210.58s — 🔴 SUSPECT (terms not in context: Jordan Baker, Based)

> Based on the provided text, here is who Jay Gatsby is and what his pursuit/conception is:  **Who is
> Jay Gatsby?** * He is "Jay Gatsby of West Egg, Long Island." * He "sprang from his Platonic
> conception of himself" and is described as "a son of God" who "must be about His Father’s business."
> * He was invented by a seventeen-year-old boy (himself), a conception to which he remained faithful
> to the end.  * His actual parents were "shiftless and unsuccessful farm people," though his
> imagination never accepted them as his parents. * He once told Jordan Baker that he was an "Oxford
> man."  **What is his dream/conception?** While the text does not explicitly use the word "dream," it
> describes his core ambitions and visions: * He is dedicated to "the service of a vast, vulgar, and
> meretricious beauty." * He envisioned climbing a ladder (formed by the blocks of a sidewalk) to a
> "secret place above the trees" where, if he climbed alone, he could "suck on the pap of life, gulp
> down the incomparable milk of wonder."

**nomic-embed-text-v1 (local, 768-dim, high quality)** — 11.37s — 🔴 SUSPECT (terms not in context: His Identity, His Origins, Based)

> Based on the provided context:  **Who is Jay Gatsby:** * **His Origins:** He was originally "young
> Gatz," the son of "shiftless and unsuccessful farm people" (whom his imagination never accepted as
> his parents).  * **His Identity:** He is "Jay Gatsby of West Egg, Long Island," a persona he
> invented when he was seventeen years old. The text describes him as a "son of God" who "sprang from
> his Platonic conception of himself."  * **His Characteristics:** He is described as "quick and
> extravagantly ambitious." At one point, he was a "penniless young man without a past" who wore a
> military uniform. * **His Achievements/History:** He is a decorated military officer ("Major Jay
> Gatsby," awarded "For Valour Extraordinary") and has a souvenir photograph from his "Oxford days" at
> Trinity Quad.   **What is his dream:** While the text does not explicitly use the word "dream," it
> details his core ambitions and lifelong pursuit: * He was dedicated to serving "a vast, vulgar, and
> meretricious beauty" (referred to as being "about His Father’s business"). * He was entirely
> faithful to the end to the "Platonic conception of himself" that he invented as a seventeen-year-old
> boy. * As a young man, his ambition was sparked by a yacht that "represented all the beauty and
> glamour in the world."

### Q2: What does the green light symbolize?

**all-MiniLM-L6-v2 (local, 384-dim, fast)** — 36.50s — 🔴 SUSPECT (terms not in context: Based)

> Based on the provided context, the green light symbolizes "the orgiastic future that year by year
> recedes before us." It is also associated with Gatsby's dream, which seemed so close to him that he
> felt he "could hardly fail to grasp it," even though it was already behind him.

**all-mpnet-base-v2 (local, 768-dim, balanced)** — 49.03s — 🔴 SUSPECT (terms not in context: Based)

> Based on the provided context, the green light symbolizes:  * **Gatsby's dream:** A dream that "must
> have seemed so close that he could hardly fail to grasp it," though it was already behind him. *
> **"The orgiastic future":** A future "that year by year recedes before us," which eludes us but
> prompts us to "run faster, stretch out our arms further." * **An "enchanted object" of "colossal
> significance":** It represented the immense distance that separated Gatsby from Daisy, seeming
> "almost touching her" and "as close as a star to the moon" before that colossal significance
> vanished.

**nomic-embed-text-v1 (local, 768-dim, high quality)** — 2.97s — 🔴 SUSPECT (terms not in context: Based)

> Based on the provided text, the green light, which is located at the end of Daisy’s dock, symbolizes
> "the orgiastic future that year by year recedes before us."

### Q3: Describe the relationship between Gatsby and Daisy.

**all-MiniLM-L6-v2 (local, 384-dim, fast)** — 14.79s — 🔴 SUSPECT (terms not in context: Secretive Meetings, Intense Devotion, Based)

> Based on the provided text, the relationship between Gatsby and Daisy is characterized by the
> following details:  * **Gatsby's Intense Devotion:** Gatsby committed himself to following Daisy as
> if she were a "grail." He viewed her as an extraordinary "nice" girl and "felt married to her," even
> after she vanished into her rich, full life and left him with nothing.  * **Secretive Meetings:**
> Gatsby wanted to see Daisy but did not want her to know about the arrangement beforehand, instead
> having Nick invite her to tea. At a party, they danced together (a "graceful, conservative foxtrot")
> and sat on Nick's steps together for half an hour while Nick kept watch. * **The Conflict Over Her
> Marriage:** Gatsby insists that Daisy is leaving her husband, Tom, and asserts with a touch of panic
> that Tom is not going to take care of her anymore. While Daisy admits she cannot truthfully say she
> "never loved Tom," she does state with a visible effort that she is leaving him. Gatsby also insists
> on speaking to Daisy alone when she is excited.

**all-mpnet-base-v2 (local, 768-dim, balanced)** — 67.31s — 🔴 SUSPECT (terms not in context: Idealization, Intimacy, Based)

> Based on the provided context, the relationship between Gatsby and Daisy is characterized by the
> following:  *   **Intimacy and Idealization:** Gatsby is deeply captivated by Daisy. He kisses her
> "curious and lovely mouth" and is highly drawn to her "husky" and "charming" voice. He associates
> her with the "youth and mystery that wealth imprisons and preserves," viewing her as "gleaming like
> silver, safe and proud above the hot struggles of the poor." *   **Secrecy and Discretion:** They
> conduct a secret affair, with Daisy visiting Gatsby "quite often—in the afternoons." To prevent
> gossip about these visits, Gatsby completely dismantles his household staff ("the whole caravansary
> had fallen in like a card house") because of the "disapproval in her eyes" and his desire for
> servants who wouldn't talk. *   **Extreme Tension and Awkwardness:** Despite their closeness, their
> interactions can be highly strained. During a reunion, Daisy speaks in a "clear artificial note"
> while Gatsby, with "distraught eyes," maintains a "strained counterfeit of perfect ease" as Daisy
> sits "frightened but graceful."  *   **Gatsby's Desire to Erase the Past:** Gatsby wants Daisy to
> completely sever her ties with the man who claims to love her (who goes on "sprees"). Gatsby
> earnestly urges Daisy to tell him "the truth—that you never loved him—and it’s all wiped out
> forever."

**nomic-embed-text-v1 (local, 768-dim, high quality)** — 5.85s — 🔴 SUSPECT (terms not in context: Year History, Beliefs, Based)

> Based on the provided context, the relationship between Gatsby and Daisy is characterized by the
> following details:  * **A Five-Year History of Love:** Gatsby states that he and Daisy have loved
> each other for five years, though they were unable to meet during that time.  * **Gatsby's Beliefs
> and Expectations:** Gatsby believes that Daisy never loved her husband, Tom, and only married him
> because Gatsby was poor and she was tired of waiting for him. He insists that Daisy has only ever
> loved him in her heart, and he desperately wants her to tell Tom that she never loved him so they
> can wipe the past away forever. * **Daisy's Conflicting Feelings:** While Daisy asserts (with a
> visible effort) that she is leaving Tom, she cannot fully align with Gatsby's version of their past.
> She admits in a pitiful voice that she cannot say she never loved Tom, because "it wouldn't be
> true."  * **Tension and Panic:** Gatsby becomes highly excited and shows "a touch of panic" when his
> perception of their relationship and her feelings is challenged by Daisy's admission and Tom's
> refusal to let her go.

### Q4: Who is Nick Carraway and how does he know Gatsby?

**all-MiniLM-L6-v2 (local, 384-dim, fast)** — 7.35s — 🔴 SUSPECT (terms not in context: Jordan Baker, Who Nick Carraway, Based)

> Based on the provided context:  * **Who Nick Carraway is:** He is the narrator of the story
> (referred to by others as "Nick" and "Mr. Carraway").  * **How he knows Gatsby:** The provided
> context does not explain how Nick and Gatsby originally met or how they know each other. It only
> shows that Nick is an acquaintance or guest of Gatsby (whom Gatsby calls "old sport") and that Nick
> is highly curious about Gatsby's identity, having only recently learned what he looks like and
> asking Jordan Baker, "Who is he?" and "What does he do?"

**all-mpnet-base-v2 (local, 768-dim, balanced)** — 19.70s — 🔴 SUSPECT (terms not in context: Carraway, After Mr, Based)

> Based on the provided context, there is no mention of the last name "Carraway," and the text does
> not explain who Nick is or how he knows Gatsby.   In fact, the context indicates that the narrator
> (implied to be Nick) does not initially know Gatsby at all. After Mr. Gatsby identifies himself, the
> narrator has to ask Jordan, "Who is he?" and "Where is he from, I mean? And what does he do?" The
> text only reveals that they are in the same room together at one point, that Gatsby addresses the
> narrator as "old sport," and that Gatsby "told me all this very much later."

**nomic-embed-text-v1 (local, 768-dim, high quality)** — 5.46s — 🔴 SUSPECT (terms not in context: Based)

> Based on the provided context, there is no mention of a character named "Nick" (only "Mr. Carraway"
> or "Carraway"), and the text does not explain how he knows Gatsby.   The context only reveals that
> they are acquainted: Mr. Carraway goes to Gatsby's house to check on him when he is worried, and
> Gatsby later calls him on the phone, addressing him as "old sport" and explaining why he fired his
> servants.

### Q5: How does Gatsby die?

**all-MiniLM-L6-v2 (local, 384-dim, fast)** — 4.13s — 🔴 SUSPECT (terms not in context: Based)

> Based on the provided context, it is not explicitly stated how Gatsby dies. The text only mentions
> "the body" and his father's remark, "It was a madman... He must have been mad," suggesting a madman
> was involved, but it does not provide the specific cause or details of his death.

**all-mpnet-base-v2 (local, 768-dim, balanced)** — 12.05s — 🔴 SUSPECT (terms not in context: Based)

> Based on the provided context, it is not mentioned how Gatsby dies. The text only refers to his
> "body" and his father mentioning a "madman," but it does not provide the specific details or cause
> of his death.

**nomic-embed-text-v1 (local, 768-dim, high quality)** — 3.10s — 🔴 SUSPECT (terms not in context: Based)

> Based on the provided context, it is not mentioned how Gatsby dies. The text only notes that he is
> dead (referring to "taking the body West" and his father's grief) and describes him heading to the
> pool with a pneumatic mattress, but it does not explain the cause or manner of his death.
