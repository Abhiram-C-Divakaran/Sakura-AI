import os
import sys
import uuid
import shutil
from sqlalchemy.orm import Session

# Setup python path to import database and parser/manager
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database.db import SessionLocal
from database.models import User, Document, DocumentChunk
from rag.ingestion.parser import DocumentParser
from rag.embeddings.manager import EmbeddingManager

OLD_PROJECT_DIR = r"c:\Users\Abhiram\Music\AVA\Project\backend"
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploaded_documents")

def main():
    if not os.path.exists(OLD_PROJECT_DIR):
        print(f"Error: Old project directory {OLD_PROJECT_DIR} not found.")
        return

    if not os.path.exists(UPLOAD_DIR):
        os.makedirs(UPLOAD_DIR, exist_ok=True)

    db = SessionLocal()
    try:
        # Get or create operator_zero
        user = db.query(User).filter_by(username="operator_zero").first()
        if not user:
            print("operator_zero not found in database. Searching for any existing user...")
            user = db.query(User).first()
            if not user:
                print("No users found. Creating a default operator_zero...")
                from auth.manager import AuthManager
                hashed = AuthManager.hash_password("securepassword123")
                user = User(username="operator_zero", hashed_password=hashed)
                db.add(user)
                db.commit()
                db.refresh(user)

        print(f"Ingesting documents for user: {user.username} ({user.id})")

        # Ingest target files
        files_to_ingest = ["llm.py", "Memory.py", "database.py", "ml_pipeline.py", "main.py", "index.html"]
        parser = DocumentParser()
        embed_mgr = EmbeddingManager()

        for filename in files_to_ingest:
            filepath = os.path.join(OLD_PROJECT_DIR, filename)
            if not os.path.exists(filepath):
                print(f"File {filename} not found in {OLD_PROJECT_DIR}, skipping.")
                continue

            print(f"Processing {filename}...")

            # Save a copy to uploaded_documents
            file_id = uuid.uuid4()
            ext = os.path.splitext(filename)[1]
            dest_filename = f"{file_id}{ext}"
            storage_path = os.path.join(UPLOAD_DIR, dest_filename)
            shutil.copy2(filepath, storage_path)

            mime_type = "text/plain" if ext != ".html" else "text/html"

            # Create document record
            doc = Document(
                id=file_id,
                user_id=user.id,
                filename=filename,
                mime_type=mime_type,
                storage_path=storage_path
            )
            db.add(doc)
            db.commit()
            db.refresh(doc)

            # Parse and chunk
            raw_text = parser.parse_file(storage_path, doc.mime_type)
            chunks = parser.get_chunks(raw_text)
            
            print(f"Generated {len(chunks)} chunks for {filename}.")
            
            # Embed chunks
            contents = [c["content"] for c in chunks]
            embeddings = embed_mgr.get_embeddings(contents)

            for i, chunk in enumerate(chunks):
                db_chunk = DocumentChunk(
                    document_id=doc.id,
                    chunk_index=chunk["chunk_index"],
                    content=chunk["content"],
                    embedding=embeddings[i],
                    metadata_json=chunk["metadata"]
                )
                db.add(db_chunk)

            db.commit()
            print(f"Finished ingesting {filename} successfully.")

        print("All old project source files have been parsed, chunked, embedded, and saved to the RAG knowledge base!")

    except Exception as e:
        db.rollback()
        print(f"Error during ingestion: {e}")
        raise e
    finally:
        db.close()

if __name__ == "__main__":
    main()
