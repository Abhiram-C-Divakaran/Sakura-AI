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
        return "Adjusting tracking... Beep! 📟 I notice this issue is recurring. I'm escalating your connection to Neo-Tokyo Senior Operations. Standby while we sync analog signal levels."
        
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
        solution = "Checking system registers... 💾 I found the double charge on your tape record! I've initiated a direct charge reversal to your bank terminal. It'll take 3-5 standard boot cycles (business days) to clear."
        if any("refund" in s.lower() or "billing" in s.lower() for s in failed_solutions):
            solution = "System anomaly! Since the automatic charge reversal failed, I've manually locked this transaction register. Could you read me the Invoice ID printed on your CRT terminal?"
        return solution
        
    elif intent == "login_issue":
        solution = "Cleaning magnetic tape heads... 📼 Try clearing your browser cache and cookies, then hit password reset on the Neo-Tokyo auth portal. Let me know if the verification packet arrives!"
        if any("forgot" in s.lower() or "cache" in s.lower() for s in failed_solutions):
            solution = "Access error! Since the reset email isn't routing, let's bypass the main stack. I've generated a temporary hardware bypass token. Should I transmit it to your backup terminal?"
        return solution
        
    elif intent == "app_crash":
        solution = "Static distortion detected! 🖥️ The console is freezing. Let's try power cycling: close the terminal completely, restart your operating system, and make sure your firmware is up-to-date."
        if any("restart" in s.lower() or "store" in s.lower() for s in failed_solutions):
            solution = "Thermal overload! Restarting didn't clear the error registers. Please dump the stack trace or send a screenshot of the display so I can submit it to the hardware lab."
        return solution

    elif intent == "performance_issue":
        solution = "Adjusting tracking... ⚙️ If the latency is high, check your dial-up speed (5Mbps recommended) and kill any background compiler scripts on your system."
        return solution

    elif intent == "connectivity":
        solution = "Signal degradation! Check the coaxial cable, verify your router power cells, and verify if other nodes on the network are responding."
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
