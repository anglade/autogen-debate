# IMPLEMENTATION GUIDE: Conversation vs Conversation+ [Beta]

## OVERVIEW
Split conversation mode into two versions:
1. **Conversation** (original) — No Moderator, stable, production
2. **Conversation+ [Beta]** — With Moderator + RED/GREEN logic, testing
3. **Debate** (unchanged)

---

## FRONTEND CHANGES

### 1. Debate Setup UI (frontend/src/components/DebateSetup.jsx)

**Current state:** Step 1 = "Debate" / "Conversation" toggle → Step 2 = Sequential/Dynamic/Manual (debate only)

**New state:** Step 1 = 3-way toggle (mutually exclusive)
- ☑ Debate
- ☑ Conversation (original)
- ☑ Conversation+ [Beta]

**UI Logic:**
```javascript
// Step 1: Mode Selection
const modeOptions = [
  { value: 'debate', label: 'Debate' },
  { value: 'conversation', label: 'Conversation' },
  { value: 'conversation_beta', label: 'Conversation+ [Beta]' }
];

// Step 2 shown only if mode === 'debate'
{debateMode === 'debate' && (
  <div>Debate Style: Sequential / Dynamic / Manual</div>
)}

// No step 2 for conversation or conversation_beta
```

**POST to /api/debate/start:**
```javascript
{
  question: "...",
  style: 'debate' | 'conversation' | 'conversation_beta',
  debateMode: 'sequential' | 'dynamic' | 'manual' // only if style === 'debate'
}
```

---

## BACKEND CHANGES

### 2. Flask App (app.py)

**Modify `/api/debate/start` endpoint:**

```python
@app.route('/api/debate/start', methods=['POST'])
def start_debate():
    data = request.json
    question = data.get('question')
    style = data.get('style', 'conversation_beta')  # debate, conversation, conversation_beta
    debate_mode = data.get('debateMode', 'dynamic')  # only used if style == 'debate'
    
    debate_id = str(uuid.uuid4())
    
    # Determine which debate runner to use
    if style == 'debate':
        thread = threading.Thread(
            target=run_debate_mode,
            args=(debate_id, question, debate_mode)
        )
    elif style == 'conversation':
        thread = threading.Thread(
            target=run_conversation_mode,
            args=(debate_id, question, include_moderator=False)
        )
    elif style == 'conversation_beta':
        thread = threading.Thread(
            target=run_conversation_mode,
            args=(debate_id, question, include_moderator=True)
        )
    
    thread.start()
    debates[debate_id] = {'status': 'running', ...}
    
    return jsonify({'debate_id': debate_id})
```

---

### 3. debate_engine.py

**Existing code:**
- `_run_debate()` → handles debate mode (sequential/dynamic/manual)
- `_run_conversation()` → handles conversation mode (no moderator currently)

**New structure:**

```python
def _run_conversation(
    self,
    user_question,
    include_moderator=False,  # NEW PARAMETER
    style='dynamic'
):
    """
    Run conversation mode.
    
    Args:
        user_question: Original question
        include_moderator: If True, add Moderator agent + RED/GREEN logic
        style: Always 'dynamic' for conversation mode
    """
    
    # ... existing setup code ...
    
    message_count = 0
    red_light_checks = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]  # Every 10
    green_light_checks = [30, 50, 60, 70, 80, 90]  # Decay pattern, then every 10 after
    
    conversation_history = []
    
    while not self.end_debate_event.is_set():
        # ... existing group chat logic ...
        
        message = next_message  # from GroupChatManager
        message_count += 1
        conversation_history.append(message)
        
        # --- RED LIGHT CHECK (every 10 messages) ---
        if include_moderator and message_count in red_light_checks:
            self._trigger_red_light(
                user_question=user_question,
                conversation_so_far=conversation_history[-5:]  # last 5 messages for context
            )
        
        # --- GREEN LIGHT CHECK (30, 50, 60, 70, 80, 90, then every 10) ---
        if include_moderator and message_count in green_light_checks:
            consensus = self._trigger_green_light(
                user_question=user_question,
                conversation_so_far=conversation_history[-5:]
            )
            if consensus:
                # All agents said yes to consensus
                self._run_judge_finale()
                break
        
        # ... rest of existing logic ...
    
    if include_moderator:
        self.update_status(f"Conversation complete. Message count: {message_count}")
```

---

### 4. Moderator RED LIGHT Logic

```python
def _trigger_red_light(self, user_question, conversation_so_far):
    """
    RED LIGHT: Every 10 messages, ask agents to reconnect to original question.
    
    Moderator asks: "You've been discussing [current work]. 
    Now answer the original question: [ORIGINAL_QUESTION]"
    """
    
    # Build summary of recent discussion
    recent_themes = self._extract_themes(conversation_so_far)
    
    moderator_message = f"""
You've been developing {recent_themes}. 
Now let's reconnect to the core question: **{user_question}**

Based on what you've just discussed, what's your direct answer to this question?
Keep it tight: one clear position + one key reason.
"""
    
    # Add Moderator to conversation
    self.chat_manager.append_message(
        "moderator",
        moderator_message,
        "function"
    )
    
    # Trigger one round of responses (each agent responds once to re-anchor)
    for agent_name in self.active_agents:  # Skip moderator itself
        if agent_name != "moderator":
            # Force agent to respond to moderator's question
            response = self._get_agent_response(agent_name, moderator_message)
            self.chat_manager.append_message(agent_name, response, "function")
            self.update_status(f"{agent_name} re-anchored to original question.")
```

---

### 5. Moderator GREEN LIGHT Logic

```python
def _trigger_green_light(self, user_question, conversation_so_far):
    """
    GREEN LIGHT: At 30, 50, 60, 70, 80, 90, then every 10, ask for consensus.
    
    Returns:
        True if consensus reached (all yes)
        False if mixed or persistent no
    """
    
    moderator_consensus_query = f"""
It seems we may be reaching a point where we can assess our progress. 
Does everyone agree we've sufficiently addressed the original question: **{user_question}**?

Please respond with just "yes" or "no" and a brief reason (one sentence).
"""
    
    # Add moderator query
    self.chat_manager.append_message(
        "moderator",
        moderator_consensus_query,
        "function"
    )
    
    # Collect votes from all active agents
    votes = {}
    vote_reasons = {}
    
    for agent_name in self.active_agents:
        if agent_name != "moderator":
            response = self._get_agent_response(agent_name, moderator_consensus_query)
            votes[agent_name] = "yes" in response.lower()
            vote_reasons[agent_name] = response
            
            self.chat_manager.append_message(agent_name, response, "function")
            self.update_status(f"{agent_name}: {'YES' if votes[agent_name] else 'NO'}")
    
    # Analyze votes
    yes_count = sum(1 for v in votes.values() if v)
    total = len(votes)
    
    if yes_count == total:
        # ALL YES = CONSENSUS REACHED
        self.update_status("✓ Consensus reached. Proceeding to Judge verdict.")
        return True
    
    elif yes_count >= total - 1:
        # Mixed but close
        self.update_status(f"Mixed votes ({yes_count}/{total}). Continuing conversation.")
        return False
    
    else:
        # Significant disagreement
        self.update_status(f"Significant disagreement ({yes_count}/{total}). Continuing conversation.")
        
        # If this is the 3rd+ persistent no from Devil's Advocate or Domain Expert, escalate
        if self._should_escalate(votes, conversation_so_far):
            self._escalate_consensus_loop()
        
        return False
```

---

### 6. Escalation Logic (message 80+)

```python
def _escalate_consensus_loop(self):
    """
    If persistent no votes at message 80+, offer choice to user.
    """
    escalation_message = """
We've built significant depth and checked consensus multiple times. 
The disagreement seems structural — you have differing views on how to weight and prioritize factors. 
This is legitimate.

**Ready to proceed to Judge verdict with the analysis we have, or continue refining?**
"""
    
    self.update_status(escalation_message)
    # User can click "End & Get Verdict" or "Keep Going"
```

---

### 7. Message Count Tracking

```python
class ConversationRunner:
    def __init__(self, ...):
        self.message_count = 0
        self.moderator_enabled = False
    
    def run_conversation(self, ..., include_moderator=False):
        self.moderator_enabled = include_moderator
        
        # In main loop:
        self.message_count += 1
        
        if self.moderator_enabled:
            # Check triggers
            if self.message_count % 10 == 0:  # Every 10
                self._trigger_red_light(...)
            
            if self.message_count in [30, 50, 60, 70, 80, 90] or \
               (self.message_count > 90 and self.message_count % 10 == 0):
                self._trigger_green_light(...)
```

---

## MODERATOR AGENT CONFIGURATION

### 8. agents.py

**Keep existing moderator definition, but ADD a flag:**

```python
# In create_agents()
moderator = ConversationAgent(
    name="moderator",
    system_message=MODERATOR_SYSTEM_PROMPT,  # (from moderator_system_prompt.md)
    llm_config=get_openai_llm_config(),
    is_system_agent=True,  # NEW
    visible_in_beta_only=True  # NEW
)

# Moderator only added to group chat if include_moderator=True
if include_moderator:
    groupchat.add_agent(moderator)
```

---

## AGENT LIBRARY CHANGES

### 9. frontend/src/components/AgentLibrary.jsx

**Display logic:**

```javascript
const isSystemAgent = agent.name === "moderator";
const isBetaOnly = agent.name === "moderator";

return (
  <div className="agent-card">
    {isSystemAgent && <span className="badge">SYSTEM AGENT</span>}
    {isBetaOnly && currentMode === "conversation_beta" && (
      <span className="badge beta">Beta Only</span>
    )}
    
    {isSystemAgent ? (
      <p className="description">
        Detects drift and checks for consensus. Active in Conversation+ [Beta] only.
      </p>
    ) : (
      <p className="description">{agent.description}</p>
    )}
    
    {isSystemAgent && (
      <p className="status">Non-editable • System agent</p>
    )}
  </div>
);
```

---

## FILES TO MODIFY

| File | Changes |
|------|---------|
| `frontend/src/components/DebateSetup.jsx` | 3-way toggle (Debate / Conversation / Conversation+ [Beta]) |
| `frontend/src/components/AgentLibrary.jsx` | Show Moderator with SYSTEM AGENT badge; grayed out unless beta mode |
| `app.py` | Route `style` parameter to correct backend function |
| `debate_engine.py` | Split `_run_conversation()` into two paths based on `include_moderator` |
| `agents.py` | Add `is_system_agent` flag to Moderator; conditionally add to group chat |
| `moderator_system_prompt.md` | Import into agents.py as `MODERATOR_SYSTEM_PROMPT` |

---

## TESTING SEQUENCE

1. **Test original Conversation mode** (include_moderator=False)
   - Should behave identically to current version
   - No Moderator appears
   - No RED/GREEN triggers

2. **Test Conversation+ [Beta] mode** (include_moderator=True)
   - Moderator appears at message 10, 20, 30, etc. (RED LIGHT)
   - Moderator asks consensus at message 30, 50, 60, 70, 80, 90 (GREEN LIGHT)
   - Can iterate on Moderator prompts without affecting Conversation

3. **Refinement loop**
   - Adjust RED LIGHT re-anchoring language
   - Adjust GREEN LIGHT consensus prompts
   - Tune escalation threshold
   - Keep Conversation unchanged for production use

---

## ROLLBACK STRATEGY

If Conversation+ [Beta] has issues:
1. Original Conversation mode is unaffected
2. Simply disable beta in UI by removing from modeOptions
3. No impact to Debate mode
4. Can continue testing in separate builds

---

## NEXT STEPS

1. Implement frontend toggle (3-way)
2. Implement backend routing (style parameter)
3. Add Moderator to agents.py with is_system_agent flag
4. Implement RED/GREEN logic in debate_engine.py
5. Test each mode independently
6. Iterate on Moderator prompts based on test results

---

## MODERATOR SYSTEM PROMPT REFERENCE

**File:** `/home/claude/moderator_system_prompt.md`

Key sections:
- RED LIGHT: Every 10 messages, re-anchor to original question
- GREEN LIGHT: At 30, 50, 60, 70, 80, 90, then every 10 messages, probe for consensus
- Escalation: At message 80+, if persistent no votes, offer choice to continue or end
- Timing table: Shows exact message counts for each trigger

---

## CONFIG SUMMARY

**Mode Routes:**
```
style='debate' + debateMode='sequential|dynamic|manual'
  → run_debate_mode()

style='conversation'
  → run_conversation_mode(include_moderator=False)

style='conversation_beta'
  → run_conversation_mode(include_moderator=True)
```

**Moderator Triggers (Beta Only):**
- Messages: 10, 20, 30, 40, 50, 60, 70, 80, 90, 100+ (every 10)
- RED at: 10, 20, 30, 40, 50, 60, 70, 80, 90, 100+ (all even 10s)
- GREEN at: 30, 50, 60, 70, 80, 90, 100+ (first at 30, then +20, then +10s)

