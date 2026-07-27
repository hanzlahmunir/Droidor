# Day 3 · Experiment 8 — Multi-Tool Agent

Agent has 4 tools; we test whether it routes each question to the RIGHT one (esp. counting, which retrieval cannot do).

## Tool Routing

| Question | Tools chosen (in order) |
|---|---|
| How many times is the green light mentioned i | count_mentions(green light) |
| What is the exact wording around 'so we beat  | search_book("beat on" "Gatsby") -> get_excerpt_around(so we beat on) |
| Who are the main characters, and how many tim | list_characters -> count_mentions(Gatsby) |
| How many times does the word 'money' appear? | count_mentions(money) |

## Answers

### How many times is the green light mentioned in the book?

**Tools:** ['count_mentions']

> The phrase **“green light”** appears **5 times** in *The Great Gatsby*.

### What is the exact wording around 'so we beat on, boats'?

**Tools:** ['search_book', 'get_excerpt_around']

> The exact line in *The Great Gatsby* is:

**“So we beat on, boats against the current, borne back ceaselessly into the past.”**

### Who are the main characters, and how many times is Gatsby named?

**Tools:** ['list_characters', 'count_mentions']

> The main characters in *The Great Gatsby* are:

- Nick Carraway (the narrator)  
- Jay Gatsby  
- Daisy Buchanan  
- Tom Buchanan  
- Jordan Baker  
- Myrtle Wilson  
- George Wilson  
- Meyer Wolfsheim  

The name “Gatsby” appears **265 times** in the novel.

### How many times does the word 'money' appear?

**Tools:** ['count_mentions']

> The word **“money”** appears **23 times** in *The Great Gatsby*.


## Takeaway

- The agent must recognize that **counting** questions need `count_mentions`, not `search_book` — retrieval returns relevant chunks but cannot produce an exact count. Correct routing here is the core test of multi-tool reasoning.