import re

def local_mock_response(prompt: str) -> str:
    """
    Simulates a smart character response if all external LLM adapters fail.
    Inherits character state and constraints from prompt content context.
    """
    # 1. Parse intent
    intent_match = re.search(r"Detected intent:\s*(\w+)", prompt)
    intent = intent_match.group(1) if intent_match else "general_inquiry"
    
    # 2. Parse issue frequency
    freq_match = re.search(r"Issue frequency:\s*(\d+)", prompt)
    frequency = int(freq_match.group(1)) if freq_match else 0
    
    # 3. Parse current message
    msg_match = re.search(r"Current message:\s*(.*)", prompt, re.DOTALL)
    message = msg_match.group(1).split("\n")[0].strip() if msg_match else ""
    
    # 4. Check for escalation condition
    if frequency > 2:
        return "I notice this issue has recurred multiple times. I am escalating your session to Senior Operations for priority investigation. Please stand by while I package our diagnostic logs."
        
    # 5. Extract failed solutions (blacklisted memory)
    failed_solutions = []
    if "FAILED solutions — DO NOT suggest these:" in prompt:
        try:
            parts = prompt.split("FAILED solutions — DO NOT suggest these:")
            if len(parts) > 1:
                section = parts[1].split("\n\n")[0]
                failed_solutions = [line.strip("- ").strip() for line in section.split("\n") if line.strip()]
        except Exception:
            pass

    # 6. Generate character-themed answers matching rules
    if intent == "billing_issue":
        solution = "I have investigated your account transactions. I identified the duplicate charge in the billing ledger and initiated a full reversal. It will reflect on your statement within 3-5 business days."
        if any("refund" in s.lower() or "billing" in s.lower() for s in failed_solutions):
            solution = "Since the automatic charge reversal could not be completed, I have flagged this transaction for manual review. Could you please confirm your invoice or transaction ID?"
        return solution
        
    elif intent == "login_issue":
        solution = "Let's resolve your authentication issue. Please clear your browser cache and cookies, then use the password reset link. A verification link will be dispatched to your registered email."
        if any("forgot" in s.lower() or "cache" in s.lower() for s in failed_solutions):
            solution = "Since the standard reset email is not reaching your inbox, I have generated a temporary verification token. Would you like me to dispatch it to your backup contact method?"
        return solution
        
    elif intent == "app_crash":
        solution = "I have analyzed the application crash report. Let's restart the application service and verify that your system runtime meets all environment requirements."
        if any("restart" in s.lower() or "store" in s.lower() for s in failed_solutions):
            solution = "The restart did not resolve the issue. Please provide the stack trace or terminal logs so we can diagnose the exact module failure."
        return solution

    elif intent == "performance_issue":
        solution = "To optimize system latency, please verify your network connection and inspect resource utilization for any runaway background processes."
        return solution

    elif intent == "connectivity":
        solution = "Network connection issue detected. Please check your network adapter settings, gateway DNS, and confirm if upstream services are reachable."
        return solution

    elif intent == "code_generation":
        solution = """Here is a clean, idiomatic implementation with test cases:

```python
def solve(items: list) -> list:
    \"\"\"
    Process and return sorted unique items.
    \"\"\"
    return sorted(list(set(items)))

# Example verification:
if __name__ == "__main__":
    test_data = [4, 2, 5, 2, 3, 1, 4]
    result = solve(test_data)
    print(f"Result: {result}")
    assert result == [1, 2, 3, 4, 5], "Test failed!"
    print("All tests passed successfully.")
```
Let me know if you would like me to add error handling, async support, or port this to TypeScript or another language!"""
        return solution

    else:
        return "I am ready to assist you. Tell me what code, software architecture, algorithm, or technical question you would like to work on!"
