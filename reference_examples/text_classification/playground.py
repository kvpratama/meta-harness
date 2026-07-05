"""Quick API connectivity test using existing LLM infrastructure."""
import argparse
import sys
import time
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from text_classification.llm import LLM

# PROMPT = "What is the capital of Nigeria? Answer in one word."
PROMPT = "You are an expert organic chemist specializing in retrosynthesis analysis.\n\nRetrosynthesis Problem:\nContext: The reaction type is Reductions.\nInput: Cc1c(-c2ccc(=O)n(Cc3cccc(F)c3F)c2)c2cc(F)ccc2n1CCO\n"
TIMEOUT = 600


def main():
    parser = argparse.ArgumentParser(description="Test LLM API connectivity")
    parser.add_argument("--model", default="gemini/gemma-4-31b-it")
    parser.add_argument("--api-key", default=None, help="Set GEMINI_API_KEY")
    parser.add_argument("--api-base", default=None)
    parser.add_argument("--timeout", type=int, default=TIMEOUT)
    parser.add_argument("--temperature", type=float, default=0.0)
    args = parser.parse_args()

    if args.api_key:
        import os
        os.environ["GEMINI_API_KEY"] = args.api_key

    llm = LLM(
        model=args.model,
        api_base=args.api_base,
        temperature=args.temperature,
        # max_tokens=64,
    )

    print(f"Model: {args.model}")
    print(f"API base: {args.api_base or '(default)'}")
    print(f"Timeout: {args.timeout}s")
    print(f"Prompt: {PROMPT}")
    print("---", flush=True)

    result = {"done": False, "response": None, "error": None, "elapsed": None}

    def call_llm():
        t0 = time.time()
        try:
            resp = llm(PROMPT)
            result["elapsed"] = time.time() - t0
            result["response"] = resp
        except Exception as e:
            result["elapsed"] = time.time() - t0
            result["error"] = e
        result["done"] = True

    t = threading.Thread(target=call_llm, daemon=True)
    t.start()
    t.join(timeout=args.timeout)

    if not result["done"]:
        print(f"TIMEOUT after {args.timeout}s - no response from API")
        print("Process likely stuck on SSL read (as seen with gemini/gemma-4-26b-a4b-it without credentials)")
    elif result["error"]:
        print(f"FAILED after {result['elapsed']:.1f}s")
        print(f"  {type(result['error']).__name__}: {result['error']}")
    else:
        print(f"OK ({result['elapsed']:.1f}s)")
        print(f"  Response: {result['response']}")
        print(f"  Usage: {llm.get_usage()}")


if __name__ == "__main__":
    main()
