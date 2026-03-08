# Demo Guide — [PRODUCT_NAME]

## The 2-Minute Script

Practice this until it's muscle memory. Every step hits a specific judging criterion.

---

### Step 1 — Set the Scene (15 seconds)
**Say to judges:**
> "I'm a commercial real estate broker who just discovered [PRODUCT_NAME].
> I'm going to call Jordan, our AI sales agent. Watch the dashboard on the
> right — you'll see Jordan's internal reasoning update in real time."

Point at the empty dashboard. Show it's blank.

---

### Step 2 — Start the Call (20 seconds)
Start the session. Jordan greets you.

**You say:**
> "Hi, I manage a team of 12 brokers at a regional firm. We do mostly office
> and retail deals. I saw your platform and wanted to learn more."

**Watch for:**
- Dashboard: Sales Stage flips from GREETING → DISCOVERY
- Customer profile starts populating: team_size = 12, deal_types = office and retail

**Judging criterion hit:** Real-time state tracking

---

### Step 3 — Trigger the Core Pain (20 seconds)
Let Jordan ask a discovery question. Answer:

**You say:**
> "Yeah, we pull all our comps from CoStar manually and drop them into Excel.
> Takes forever — usually 3 or 4 hours per report."

**Watch for:**
- Dashboard: Stage flips to PITCH
- Profile: current_tools = CoStar and Excel, pain_points = comp reports
- Tool calls panel: update_customer_profile fires, update_sales_stage fires
- Jordan immediately pivots to the comp automation pitch without asking more questions

**What to point out to judges:**
> "Notice Jordan didn't ask the next question on a list — it detected the pain
> and moved to pitch. That's intent-driven conversation, not a script."

**Judging criterion hit:** Dynamic conversation, tool calls

---

### Step 4 — The Interruption (10 seconds)
While Jordan is mid-pitch on pipeline intelligence, cut it off:

**You say (interrupting):**
> "Wait — how much does this actually cost?"

**Watch for:**
- Jordan stops instantly (within 100ms)
- Jordan answers the pricing question directly
- After answering, Jordan does NOT just resume the previous sentence

**Explicitly say to judges:**
> "Jordan stopped mid-sentence. That's Gemini Live's voice activity detection —
> no extra code required. It feels like interrupting a real person."

**Judging criterion hit:** Interruption handling (explicit criterion)

---

### Step 5 — The Vision Feature (20 seconds) — THE SHOW-STOPPER
Hold your phone to the webcam showing CoStar's website or a comp report.

**Jordan should say something like:**
> "I can see you have CoStar open right there — that's exactly the workflow
> we eliminate. Right now you're pulling that data manually and dropping it
> into Excel. [PRODUCT_NAME] automates that entire step."

**What to say to judges:**
> "Jordan can see what the customer is showing through their webcam.
> This is Gemini's multimodal capability — same model, no extra API."

**Judging criterion hit:** Multimodal, vision, wow factor

---

### Step 6 — The Objection (15 seconds)
**You say:**
> "That's way too expensive. We already pay for CoStar."

**Watch for:**
- Stage flips to OBJECTION_HANDLING
- Jordan does NOT treat CoStar as a competitor
- Jordan reframes: "[PRODUCT_NAME] works WITH CoStar..."
- Jordan provides the ROI math: hours saved → deal opportunity

**Judging criterion hit:** Objection handling, domain knowledge

---

### Step 7 — The Close (10 seconds)
**You say:**
> "Okay, I'm interested. What would you recommend for my team?"

**Watch for:**
- Jordan calls generate_recommendation()
- Tool calls panel shows the call + result
- Jordan says: "Based on your 12-person team and the hours you mentioned
  losing on comp reports, Professional at $799 a month is the right fit."
- Jordan offers the 14-day free trial

**Judging criterion hit:** Personalized recommendation, tool use, closing

---

## Before You Walk On Stage

### Audio Checklist
- [ ] OUTPUT_RATE = 24000 confirmed in agent.py
- [ ] OUTPUT_CHUNK = 1024 confirmed in agent.py
- [ ] Voice is Aoede in PrebuiltVoiceConfig
- [ ] Interrupt test: Jordan stops within 100ms ✓

### Prompt Checklist
- [ ] generate_prompt.py has been run after latest config.json changes
- [ ] system_prompt.txt opens with a contraction in the first sentence
- [ ] system_prompt.txt contains zero markdown symbols (* # -)
- [ ] Jordan correctly handles "CoStar and Excel" in a test conversation

### Dashboard Checklist
- [ ] All 4 panels visible, font is minimum 18px
- [ ] Stage badge changes color on transition
- [ ] Profile entries show with yellow flash
- [ ] Tool calls panel shows [HH:MM:SS] timestamps
- [ ] URL is the Cloud Run public URL (not localhost)

### Vision Checklist
- [ ] Phone charged and CoStar website loaded in browser
- [ ] Webcam positioned to clearly see phone screen
- [ ] Jordan reacts to CoStar on webcam in test run

### Environment Checklist
- [ ] GEMINI_API_KEY is set
- [ ] DASHBOARD_URL is set to Cloud Run URL
- [ ] agent.py prints "Jordan from [PRODUCT_NAME] is ready"
- [ ] Cloud Run /health returns 200

---

## If Things Go Wrong

**Audio distorted or slow:**
→ Check OUTPUT_RATE is 24000, restart agent.py

**Jordan doesn't stop on interruption:**
→ Reduce OUTPUT_CHUNK to 512, restart

**Dashboard not updating:**
→ Check DASHBOARD_URL env var matches Cloud Run URL
→ Open browser console, check for CORS errors
→ Fallback: point browser at localhost:8080 (explains local deployment)

**Vision not working:**
→ Disable vision.py — skip that demo moment
→ Describe the capability verbally: "In our full version, Jordan can also see..."

**Tool calls not firing:**
→ Check docstrings in tools.py are intact
→ Fallback: Jordan answers from system prompt — still demoable

**Gemini API error:**
→ Should auto-retry — wait 5 seconds
→ Fallback: restart agent.py, skip to later in demo script

---

## Judge Q&A Prep

**"How does this scale beyond a demo?"**
> "The voice interface runs on any device with a mic. The reasoning layer is
> already on Google Cloud Run. In production you'd point it at a WebRTC
> endpoint — same architecture, any channel."

**"How do you swap domains?"**
> "One config.json change and a 5-second script run. Everything else is
> domain-agnostic. Jordan could be selling financial services software
> tomorrow with zero code changes."

**"Is this just a fancy chatbot?"**
> "The difference is that Jordan drives the conversation. It detects intent,
> decides when to move stages, calls tools when the math matters, and adapts
> its pitch based on what it learns — not what question comes next on a list."

**"What's the production deployment look like?"**
> "Dashboard API is already on Google Cloud Run. Voice loop containerizes
> to any edge device or WebRTC platform. API keys live in Secret Manager.
> Full CI/CD via GitHub Actions."
