from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import OpenAI

import sqlite3


# ==================================================
# LOAD ENVIRONMENT VARIABLES
# ==================================================

load_dotenv()

client = OpenAI()


# ==================================================
# FASTAPI APP
# ==================================================

app = FastAPI()


# ==================================================
# STATIC FILES
# ==================================================

app.mount(
    "/static",
    StaticFiles(directory="static"),
    name="static"
)


# ==================================================
# DATABASE
# ==================================================

DATABASE = "projectpulse.db"


def init_database():

    connection = sqlite3.connect(DATABASE)

    cursor = connection.cursor()

    # ----------------------------------------------
    # Conversations
    # ----------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversations (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            conversation TEXT NOT NULL,

            analysis TEXT NOT NULL,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        )
    """)


    # ----------------------------------------------
    # Action Item Feedback
    # ----------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS action_feedback (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            task TEXT NOT NULL,

            status TEXT NOT NULL,

            edited_task TEXT,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        )
    """)


    connection.commit()

    connection.close()


init_database()


# ==================================================
# HOME PAGE
# ==================================================

@app.get("/")
def home():

    return FileResponse(
        "static/index.html"
    )


# ==================================================
# REQUEST MODELS
# ==================================================

class ConversationRequest(BaseModel):

    conversation: str


class AskProjectRequest(BaseModel):

    conversation: str

    question: str


class FeedbackRequest(BaseModel):

    task: str

    status: str

    edited_task: str = ""


# ==================================================
# ANALYZE CONVERSATION
# ==================================================

@app.post("/analyze")
def analyze_conversation(
    request: ConversationRequest
):

    response = client.responses.create(

        model="gpt-5.6-luna",

        input=f"""
You are ProjectPulse AI, an intelligent
project communication assistant.

Analyze the project communication below.

Return:

1. A concise project summary.

2. Important decisions.

3. Action items with:
   - task
   - owner
   - deadline
   - priority
   - source

4. Unresolved issues with:
   - issue
   - source

IMPORTANT RULES:

- Use ONLY information from the conversation.
- Do not invent facts.
- Do not assume an owner.
- Do not assume a deadline.
- Use "Not specified" when information is missing.
- Priority must be High, Medium, or Low.
- Source must be an exact sentence or short passage
  from the original conversation.
- Keep the output practical and concise.

Project communication:

{request.conversation}
""",

        text={

            "format": {

                "type": "json_schema",

                "name": "project_analysis",

                "strict": True,

                "schema": {

                    "type": "object",

                    "properties": {

                        "summary": {
                            "type": "string"
                        },

                        "decisions": {

                            "type": "array",

                            "items": {

                                "type": "object",

                                "properties": {

                                    "decision": {
                                        "type": "string"
                                    },

                                    "source": {
                                        "type": "string"
                                    }

                                },

                                "required": [
                                    "decision",
                                    "source"
                                ],

                                "additionalProperties": False

                            }

                        },

                        "action_items": {

                            "type": "array",

                            "items": {

                                "type": "object",

                                "properties": {

                                    "task": {
                                        "type": "string"
                                    },

                                    "owner": {
                                        "type": "string"
                                    },

                                    "deadline": {
                                        "type": "string"
                                    },

                                    "priority": {
                                        "type": "string"
                                    },

                                    "source": {
                                        "type": "string"
                                    }

                                },

                                "required": [
                                    "task",
                                    "owner",
                                    "deadline",
                                    "priority",
                                    "source"
                                ],

                                "additionalProperties": False

                            }

                        },

                        "unresolved_issues": {

                            "type": "array",

                            "items": {

                                "type": "object",

                                "properties": {

                                    "issue": {
                                        "type": "string"
                                    },

                                    "source": {
                                        "type": "string"
                                    }

                                },

                                "required": [
                                    "issue",
                                    "source"
                                ],

                                "additionalProperties": False

                            }

                        }

                    },

                    "required": [
                        "summary",
                        "decisions",
                        "action_items",
                        "unresolved_issues"
                    ],

                    "additionalProperties": False

                }

            }

        }

    )


    analysis = response.output_text


    # ==================================================
    # APPLY PREVIOUS HUMAN FEEDBACK
    # ==================================================

    analysis_data = json_load(analysis)


    connection = sqlite3.connect(DATABASE)

    cursor = connection.cursor()


    cursor.execute("""
        SELECT task, status, edited_task
        FROM action_feedback
        ORDER BY id ASC
    """)


    feedback_rows = cursor.fetchall()

    connection.close()


    # ----------------------------------------------
    # Apply feedback to current AI action items
    # ----------------------------------------------

    updated_action_items = []


    for item in analysis_data["action_items"]:

        original_task = item["task"]

        latest_feedback = None


        for feedback in feedback_rows:

            feedback_task = feedback[0]

            if feedback_task == original_task:

                latest_feedback = feedback


        if latest_feedback:

            status = latest_feedback[1]

            edited_task = latest_feedback[2]


            # Edited task
            if status == "Edited" and edited_task:

                item["task"] = edited_task

                item["feedback_status"] = "Edited"


            # Approved task
            elif status == "Approved":

                item["feedback_status"] = "Approved"


            # Rejected task
            elif status == "Rejected":

                item["feedback_status"] = "Rejected"

                continue


        updated_action_items.append(item)


    analysis_data["action_items"] = updated_action_items


    # Convert back to JSON

    analysis = json_dump(analysis_data)


    # ==================================================
    # SAVE CONVERSATION TO PROJECT MEMORY
    # ==================================================

    connection = sqlite3.connect(DATABASE)

    cursor = connection.cursor()


    cursor.execute(
        """
        INSERT INTO conversations
        (conversation, analysis)
        VALUES (?, ?)
        """,
        (
            request.conversation,
            analysis
        )
    )


    connection.commit()

    connection.close()


    return {

        "analysis": analysis,

        "memory_saved": True

    }


# ==================================================
# ASK THE PROJECT
# ==================================================

@app.post("/ask")
def ask_project(
    request: AskProjectRequest
):

    connection = sqlite3.connect(DATABASE)

    cursor = connection.cursor()


    cursor.execute(
        """
        SELECT conversation, analysis
        FROM conversations
        ORDER BY created_at DESC
        LIMIT 10
        """
    )


    memories = cursor.fetchall()

    connection.close()


    memory_text = ""


    for index, memory in enumerate(
        memories,
        start=1
    ):

        old_conversation = memory[0]

        old_analysis = memory[1]


        memory_text += f"""

==============================
PROJECT MEMORY {index}
==============================

Original communication:

{old_conversation}

Previous analysis:

{old_analysis}

"""


    response = client.responses.create(

        model="gpt-5.6-luna",

        input=f"""
You are ProjectPulse AI.

You are an intelligent project communication
assistant with access to project memory.

Answer the user's question using ONLY the
project communication and project memory provided.

IMPORTANT RULES:

- Do not invent information.
- Do not make assumptions.
- If the information cannot be found, say:

"I could not find this information in the
project communication."

- Give a clear and concise answer.
- Mention the relevant source communication
  when possible.
- You may use previous project conversations.

CURRENT PROJECT COMMUNICATION:

{request.conversation}

PROJECT MEMORY:

{memory_text}

USER QUESTION:

{request.question}
"""
    )


    return {

        "answer": response.output_text,

        "memory_used": len(memories)

    }


# ==================================================
# PROJECT MEMORY COUNT
# ==================================================

@app.get("/memory")
def get_memory():

    connection = sqlite3.connect(DATABASE)

    cursor = connection.cursor()


    cursor.execute(
        """
        SELECT COUNT(*)
        FROM conversations
        """
    )


    count = cursor.fetchone()[0]

    connection.close()


    return {

        "saved_conversations": count

    }


# ==================================================
# SAVE ACTION ITEM FEEDBACK
# ==================================================

@app.post("/feedback")
def save_feedback(
    request: FeedbackRequest
):

    allowed_statuses = [

        "Approved",

        "Edited",

        "Rejected"

    ]


    if request.status not in allowed_statuses:

        return {

            "success": False,

            "message":
                "Invalid feedback status."

        }


    connection = sqlite3.connect(DATABASE)

    cursor = connection.cursor()


    cursor.execute(
        """
        INSERT INTO action_feedback
        (task, status, edited_task)
        VALUES (?, ?, ?)
        """,
        (
            request.task,
            request.status,
            request.edited_task
        )
    )


    connection.commit()

    connection.close()


    return {

        "success": True,

        "message":
            f"Action item marked as {request.status}."

    }


# ==================================================
# GET ACTION ITEM FEEDBACK
# ==================================================

@app.get("/feedback")
def get_feedback():

    connection = sqlite3.connect(DATABASE)

    cursor = connection.cursor()


    cursor.execute(
        """
        SELECT task, status, edited_task
        FROM action_feedback
        ORDER BY id ASC
        """
    )


    rows = cursor.fetchall()

    connection.close()


    feedback = []


    for row in rows:

        feedback.append({

            "task": row[0],

            "status": row[1],

            "edited_task": row[2] or ""

        })


    return {

        "feedback": feedback

    }


# ==================================================
# JSON HELPERS
# ==================================================

def json_load(text):

    import json

    return json.loads(text)


def json_dump(data):

    import json

    return json.dumps(data)