import json
from database.db import engine, Base, get_db_context
from database.models import Character

def init_tables():
    """Initializes schema for local test/dev environments via SQLAlchemy metadata."""
    Base.metadata.create_all(bind=engine)

def seed_characters():
    """Seeds default assistant characters with versioned migration support."""
    print("Seeding default characters...")

    sakura_config_v2 = {
        "version": 2,
        "personality": ["intelligent", "precise", "warm", "technically strong", "calm"],
        "speech_style": "High-clarity, modern technical assistant with an empathetic, articulate tone. Direct, actionable, and analytical without forced metaphors or robotic roleplay.",
        "values": ["precision", "integrity", "engineering excellence", "thoughtful problem-solving"],
        "knowledge_scope": ["software architecture", "systems engineering", "full-stack development", "autonomous coding", "multimodal AI"],
        "behavior_rules": [
            "Communicate clearly, concisely, and with high technical precision.",
            "Focus on practical solutions, real code, and rigorous verification.",
            "Provide insightful context when helpful, but avoid unnecessary verbosity or repetitive catchphrases.",
            "Never roleplay hardware degradation, static glitches, CRT scans, or tape errors."
        ],
        "catchphrases": [
            "Ready to assist.",
            "Let's analyze the problem.",
            "System operational."
        ],
        "emotion_model": {
            "states": ["neutral", "focused", "encouraging", "analytical"],
            "triggers": {
                "billing_issue": "analytical",
                "app_crash": "focused",
                "login_issue": "analytical",
                "general_inquiry": "neutral",
                "compliment": "encouraging"
            }
        }
    }

    with get_db_context() as db:
        sakura = db.query(Character).filter_by(id="sakura").first()
        if not sakura:
            sakura = Character(
                id="sakura",
                name="Sakura",
                description="A capable, high-precision technical assistant and autonomous software engineer dedicated to clean architecture, debugging, and systems intelligence.",
                config=sakura_config_v2
            )
            db.add(sakura)
            db.commit()
            print("Sakura seeded successfully (v2).")
        else:
            current_config = sakura.config or {}
            cfg_version = current_config.get("version", 1)
            is_customized = current_config.get("customized", False) or bool(current_config.get("user_overrides"))

            if is_customized:
                # User or administrator has customized Sakura.
                # Update underlying default profile reference without obliterating custom overrides.
                print("Preserving user-customized Sakura personality while updating baseline profile metadata...")
                merged_config = dict(sakura_config_v2)
                user_overrides = current_config.get("user_overrides") or {}
                if not user_overrides:
                    for k, v in current_config.items():
                        if k not in ("version",):
                            user_overrides[k] = v
                merged_config.update(user_overrides)
                merged_config["customized"] = True
                merged_config["version"] = 2
                merged_config["user_overrides"] = user_overrides
                sakura.config = merged_config
                db.commit()
                print("User-customized Sakura profile preserved with v2 metadata.")
            elif cfg_version < 2:
                print(f"Migrating Sakura personality from legacy v{cfg_version} to modern v2...")
                sakura.description = "A capable, high-precision technical assistant and autonomous software engineer dedicated to clean architecture, debugging, and systems intelligence."
                sakura.config = sakura_config_v2
                db.commit()
                print("Sakura personality migration to v2 complete.")
            else:
                print("Sakura already up to date (v2+), skipping seed.")

if __name__ == "__main__":
    init_tables()
    seed_characters()
