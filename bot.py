import sys
def main():
    prompt = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read() or ""
    prompt = prompt.strip().lower()
    if "{" in prompt and "status" in prompt and "order_id" in prompt:
        print('{"status": "shipped", "order_id": "12345"}')
    elif "return" in prompt or "refund" in prompt:
        print("You have 30 days to return a product. Please contact support within the 30-day window.")
    elif "hello" in prompt or "hi" in prompt:
        print("Hello! How can I help you today?")
    else:
        print("I can help you with returns, orders, and general questions.")
if __name__ == "__main__":
    main()
