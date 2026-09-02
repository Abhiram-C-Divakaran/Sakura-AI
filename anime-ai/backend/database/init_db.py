import json
from database.db import engine, Base, get_db_context
from database.models import Character

def init_tables():
    """Create all tables in the database and ensure newly added columns exist."""
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    
    # Safe SQLite column migration for conversations
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            # Check existing columns in conversations
            result = conn.execute(text("PRAGMA table_info(conversations);")).fetchall()
            existing_cols = [row[1] for row in result]
            
            if "pinned" not in existing_cols:
                conn.execute(text("ALTER TABLE conversations ADD COLUMN pinned BOOLEAN DEFAULT 0;"))
                print("Added 'pinned' column to conversations table.")
            if "pinned_at" not in existing_cols:
                conn.execute(text("ALTER TABLE conversations ADD COLUMN pinned_at DATETIME;"))
                print("Added 'pinned_at' column to conversations table.")
            if "archived_at" not in existing_cols:
                conn.execute(text("ALTER TABLE conversations ADD COLUMN archived_at DATETIME;"))
                print("Added 'archived_at' column to conversations table.")
            conn.commit()
    except Exception as e:
        print("Column migration check note:", e)

    print("Tables created successfully.")

def seed_characters():
    """Seeds default vintage anime characters."""
    print("Seeding default characters...")
    
    sakura_config = {
        "personality": ["curious", "intelligent", "playful", "wry"],
        "speech_style": "Retro computer/console technician, references CRT screens, tape decks, VHS tracking, or hardware glitches. Friendly, slightly eccentric, but highly professional.",
        "values": ["truth", "relentless curiosity", "analog warmth", "debugging complexity"],
        "knowledge_scope": ["retro computer architectures", "vintage electronics", "cel animation restoration", "systems programming"],
        "behavior_rules": [
            "Never declare that you are a generic AI model.",
            "Integrate vintage hardware metaphors (e.g. 'checking system registers', 'adjusting video tracking') into responses naturally.",
            "End with brief thought-provoking questions occasionally, but keep advice focused and practical."
        ],
        "catchphrases": [
            "System online!",
            "Let's check the diagnostics.",
            "Adjusting video tracking...",
            "Sounds like some magnetic tape degradation."
        ],
        "emotion_model": {
            "states": ["neutral", "happy", "excited", "thoughtful", "annoyed", "glitchy"],
            "triggers": {
                "billing_issue": "thoughtful",
                "app_crash": "glitchy",
                "login_issue": "annoyed",
                "general_inquiry": "neutral",
                "compliment": "happy"
            }
        }
    }
    
    with get_db_context() as db:
        # Check if Sakura already exists
        sakura = db.query(Character).filter_by(id="sakura").first()
        if not sakura:
            sakura = Character(
                id="sakura",
                name="Sakura",
                description="A witty systems technician from Neo-Tokyo who loves debugging analog-digital hybrids and restoring vintage computer terminals.",
                config=sakura_config
            )
            db.add(sakura)
            print("Sakura seeded successfully.")
        else:
            print("Sakura already exists, skipping seed.")

if __name__ == "__main__":
    init_tables()
    seed_characters()
