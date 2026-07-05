# Part 2 — The Harness Contract: the `MemorySystem` Interface

For a search to work, every candidate has to be interchangeable: the inner loop must drive any
harness the same way without knowing what's inside it. In the text-classification example, that
common shape is an abstract base class called `MemorySystem`. If you understand its five methods,
you understand the entire search space — every candidate the proposer ever writes is a subclass of
this.

## Five methods, two phases

```python
# from reference_examples/text_classification/memory_system.py, lines 61–70
class MemorySystem(ABC):
    """Memory system interface for online and offline learning.

    Args:
        llm: Callable that takes a prompt string and returns a response string.
    """

    def __init__(self, llm: LLMCallable):
        self._llm = llm
        self._prompt_local = threading.local()
```

Notice the constructor takes the LLM as an argument. The harness never *creates* a model; one is
injected. That's the frozen-model boundary from Part 1, enforced in code — a candidate can decide
*what to send* the model, but not *which model* to call.

The two abstract methods that matter most are a matched pair:

```python
# from reference_examples/text_classification/memory_system.py, lines 89–92
    @abstractmethod
    def predict(self, input: str) -> tuple[str, dict[str, Any]]:
        """Generate prediction BEFORE seeing ground truth. Returns (answer, metadata)."""
        pass
```

`predict` runs first, blind to the answer. Then — after the answer is known — `learn_from_batch`
gets a chance to update internal state. The "BEFORE seeing ground truth" comment is the whole
contract in five words: a harness must commit to an answer before it is allowed to learn from the
truth. That ordering is what makes the score honest.

The remaining three methods round out the contract: `learn_from_batch` (covered in Part 3),
`get_state`/`set_state` for checkpointing, and an optional `get_context_length`:

```python
# from reference_examples/text_classification/memory_system.py, lines 111–127
    def get_context_length(self) -> int:
        """Return the character length of context actually injected per query.

        Override in subclasses where the injected context differs from stored state
        (e.g., fewshot memories that store all examples but only inject N).
        """
        return len(self.get_state())

    @abstractmethod
    def get_state(self) -> str:
        """Return serializable state for checkpointing."""
        pass

    @abstractmethod
    def set_state(self, state: str) -> None:
        """Restore state from serialized representation."""
        pass
```

`get_state` returning a *string* is a deliberate constraint: state must serialize to text, so any
candidate's learned memory can be saved to a file, reloaded, and inspected by a human. And
`get_context_length` is the second axis the search optimizes — Part 4 plots accuracy *against*
context length, so a harness that's slightly less accurate but far cheaper can still win.

```diagram
        predict(input)                 learn_from_batch(results)
   ┌──────────────────────┐          ┌──────────────────────────┐
   │ build prompt from     │          │ now ground truth is known │
   │ stored state + input  │          │ update internal state     │
   │ → answer (no truth)   │          │ (or ignore it)            │
   └──────────┬───────────┘          └─────────────┬────────────┘
              │   answer scored against truth        │
              └──────────────────────────────────────┘
                       get_state / set_state
                       serialize the learned memory to a string
```

## The two endpoints of the search space

The repo ships two baselines that bracket what a memory system can do.

`NoMemory` is the floor — it learns nothing and just prompts the model directly:

```python
# from reference_examples/text_classification/agents/no_memory.py, lines 27–34
    def predict(self, input: str) -> tuple[str, dict[str, Any]]:
        response = self.call_llm(PROMPT.format(input=input))
        answer = extract_json_field(response, "final_answer")
        return answer, {"full_response": response}

    def learn_from_batch(self, batch_results: list[dict[str, Any]]) -> None:
        """No learning - this baseline ignores all feedback."""
        pass
```

Its `learn_from_batch` is literally `pass`. This is the control: any candidate that can't beat
"just ask the model" isn't earning its complexity.

`FewShotMemory` is the other endpoint — it remembers every labeled example and replays them as
demonstrations:

```python
# from reference_examples/text_classification/agents/fewshot_memory.py, lines 101–107
    def learn_from_batch(self, batch_results: list[dict[str, Any]]) -> None:
        """Accumulate all examples with ground truth labels."""
        for r in batch_results:
            ex = {"input": r["input"], "target": r["ground_truth"]}
            if "raw_question" in r:
                ex["raw_question"] = r["raw_question"]
            self.examples.append(ex)
```

Same interface, opposite philosophy: store everything, inject as much as fits. Most interesting
candidates live *between* these two — selective memory, summarized lessons, clustered examples —
and that "between" is exactly the territory the proposer explores in Part 5.

## What to notice

- **The LLM is injected, never constructed.** `__init__(self, llm)` is how the frozen-model
  boundary is enforced for every candidate.
- **`predict` is blind; `learn_from_batch` is informed.** The strict ordering is what keeps scores
  from leaking the answer into the prediction.
- **State is a string.** Serializable memory means every candidate can be checkpointed and read by
  a human — important when you're debugging why one harness beat another.
- **Two baselines bracket the space.** `NoMemory` (learn nothing) and `FewShotMemory` (remember
  everything) are the floor and a strong ceiling; novel candidates compete in between.

---

*Next up: Part 3 — Scoring One Candidate — how the inner loop drives `predict` and `learn_from_batch` over a dataset, in both online and offline modes, and turns a harness into a single accuracy number.*

## ✦ Check Your Understanding

1. Why does `predict` return *before* any ground truth is available, while `learn_from_batch`
   receives the truth? What would break in the search if a candidate could peek at the answer
   inside `predict`?
2. You want to build a harness that stores a short, LLM-written "lessons learned" note instead of
   raw examples. Which of the five methods do you change, and which can you inherit unchanged from
   a base like `FewShotMemory`?
3. `get_context_length` defaults to `len(self.get_state())` but `FewShotMemory` overrides it. Modify
   your mental model: for a memory that *stores* 500 examples but only *injects* 10 per query, what
   should `get_context_length` return, and why does the distinction matter for the Pareto frontier?
