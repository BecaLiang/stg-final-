import boto3
from dotenv import load_dotenv
import psycopg2
import os
import uuid
import mimetypes
from datetime import datetime
import PyPDF2
from sentence_transformers import SentenceTransformer
import numpy as np
import pytesseract
from pdf2image import convert_from_path
from PIL import Image
import tempfile
import argparse

load_dotenv()

# Connect to the database
try:
    conn = psycopg2.connect(os.getenv("DATABASE_URL"))
except psycopg2.OperationalError as e:
    print("❌ Database connection failed!")
    print(f"Error: {e}")
    print("\n💡 Hint: If you see this error, you need to either:")
    print("   1. Run 'wasp db start' in the web-app folder, or")
    print("   2. Set the DATABASE_URL properly in your .env file")
    print("\nExample DATABASE_URL format:")
    print("   DATABASE_URL=postgresql://username:password@localhost:5432/database_name")
    exit(1)

AWS_S3_ACCESS_KEY = os.getenv("AWS_S3_ACCESS_KEY")
AWS_S3_SECRET_KEY = os.getenv("AWS_S3_SECRET_KEY")
AWS_S3_REGION = os.getenv("AWS_S3_REGION")
AWS_S3_BUCKET = os.getenv("AWS_S3_BUCKET")

s3 = boto3.client(
    "s3",
    aws_access_key_id=AWS_S3_ACCESS_KEY,
    aws_secret_access_key=AWS_S3_SECRET_KEY,
    region_name=AWS_S3_REGION,
)

# Create a cursor object
cursor = conn.cursor()

# Initialize embedding model
print("Loading embedding model...")
embedding_model = SentenceTransformer('all-mpnet-base-v2')
print("Embedding model loaded successfully!")

# Customer to file mapping based on the provided image
CUSTOMER_FILE_MAPPING = {
    "ifm electronics": "ifm_purchasing guidline_vs06_pcb.pdf",
    "Pilz GmbH & Co. KG": ["PILZ_LP-SPEZIFIKATION_V2.0_en.pdf", "datasheet explanation Example.pdf"],
    "Sero GmbH": ["95.0011.0F_delivery specifications for pcbs.pdf", 
                  "Annex to 95.0011.0F_15-06-2012_signed CML.pdf",
                  "ENG_SS_115-18829_1_General Delivery Specification.pdf"],
    "Viessmann Elektronik GmbH": "KLH_4414808_05.pdf",
    "Zollner Elektronik AG": "D-13-00004_20200110 Rev 1_incl. Vendor Addendum_signed both sites.pdf",
    "Deltec": ["DELTC-Grote_Scania_SNGL-badmark-160705.pdf",
               "DELTEC-signed-140122_Annex to Hella-N67036-2013-01-29 for EMS signed by CML.pdf"],
    "E.G.O. Produktion GmbH & Co. KG": "E.G.O. PCB delivery specification LV6000000_90.03300.404_Version 11.pdf"
}

def upload_file_to_s3(file_path):
    """Upload PDF file to S3 and return file ID and metadata. Skip if already exists."""
    if not os.path.exists(file_path):
        print(f"Warning: File not found: {file_path}")
        return None
    
    base_file_name = os.path.basename(file_path)
    
    # Check if file already exists in database
    cursor.execute("""
        SELECT id FROM "File" WHERE name = %s AND type = 'application/pdf'
    """, (base_file_name,))
    existing_file = cursor.fetchone()
    
    if existing_file:
        print(f"✓ File already exists in database: {base_file_name} (ID: {existing_file[0]})")
        return existing_file[0]
    
    file_id = str(uuid.uuid4())
    file_type = 'application/pdf'
    
    # Include extension in S3 key
    file_extension = os.path.splitext(base_file_name)[1]
    key = f"{file_id}{file_extension}"
    
    try:
        with open(file_path, 'rb') as file_data:
            s3.upload_fileobj(file_data, AWS_S3_BUCKET, key)
        
        upload_url = f"https://{AWS_S3_BUCKET}.s3.{AWS_S3_REGION}.amazonaws.com/{key}"
        
        cursor.execute("""
            INSERT INTO "File" (id, "createdAt", name, type, key, "uploadUrl")
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (file_id, datetime.now(), base_file_name, file_type, key, upload_url))
        
        conn.commit()
        print(f"✓ Uploaded to S3: {base_file_name}")
        return file_id
        
    except Exception as e:
        print(f"Error uploading {base_file_name}: {e}")
        conn.rollback()
        return None

def extract_text_with_ocr(file_path):
    """Extract text from PDF using OCR for scanned/image-based PDFs."""
    chunks = []
    
    try:
        print(f"Attempting OCR extraction for: {os.path.basename(file_path)}")
        
        # Convert PDF to images
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                # Convert PDF pages to images
                images = convert_from_path(file_path, dpi=200, output_folder=temp_dir)
                total_pages = len(images)
                
                if total_pages == 0:
                    print(f"Warning: No pages could be converted to images")
                    return chunks
                
                pages_with_text = 0
                for page_num, image in enumerate(images, 1):
                    try:
                        # Use OCR to extract text from image
                        text = pytesseract.image_to_string(image, lang='eng')
                        
                        if text.strip():
                            pages_with_text += 1
                            print(f"OCR extracted text from page {page_num}")
                            
                            # Create semantic chunks
                            page_chunks = create_semantic_chunks(text, page_num, len(chunks))
                            chunks.extend(page_chunks)
                        else:
                            print(f"No text found on page {page_num} via OCR")
                            
                    except Exception as e:
                        print(f"Warning: OCR failed on page {page_num}: {e}")
                        continue
                
                print(f"OCR completed: {pages_with_text}/{total_pages} pages had extractable text")
                
            except Exception as e:
                print(f"Error converting PDF to images: {e}")
                return chunks
                
    except Exception as e:
        print(f"Error during OCR processing: {e}")
        return chunks
    
    return chunks

def extract_text_from_pdf(file_path):
    """Extract text from PDF file and return chunks with page information."""
    chunks = []
    
    try:
        with open(file_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            total_pages = len(pdf_reader.pages)
            
            if total_pages == 0:
                print(f"Warning: PDF has no pages: {os.path.basename(file_path)}")
                return chunks
            
            pages_with_text = 0
            for page_num, page in enumerate(pdf_reader.pages, 1):
                try:
                    text = page.extract_text()
                    if text.strip():
                        pages_with_text += 1
                        # Create semantic chunks that preserve sentence boundaries
                        page_chunks = create_semantic_chunks(text, page_num, len(chunks))
                        chunks.extend(page_chunks)
                except Exception as e:
                    print(f"Warning: Could not extract text from page {page_num}: {e}")
                    continue
            
            if pages_with_text == 0:
                print(f"Warning: No readable text found with standard extraction.")
                print(f"Attempting OCR for scanned/image-based PDF...")
                
                # Try OCR extraction
                ocr_chunks = extract_text_with_ocr(file_path)
                if ocr_chunks:
                    print(f"✓ OCR successful: extracted {len(ocr_chunks)} chunks")
                    return ocr_chunks
                else:
                    print(f"✗ OCR failed: no text could be extracted")
                    print(f"This PDF might be corrupted or contain only images without text.")
                    
    except Exception as e:
        print(f"Error reading PDF {file_path}: {e}")
        return []
    
    return chunks

def create_semantic_chunks(text, page_number, start_chunk_index):
    """Create semantic chunks that preserve sentence boundaries and context."""
    chunks = []
    
    # Clean and normalize text
    text = text.strip()
    if not text:
        return chunks
    
    # Split into sentences (basic sentence splitting)
    import re
    sentences = re.split(r'(?<=[.!?])\s+', text)
    
    current_chunk = ""
    chunk_index = start_chunk_index
    target_chunk_size = 800  # Target size for better semantic context
    max_chunk_size = 1200    # Maximum size before forcing a split
    
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
            
        # If adding this sentence would exceed max size, save current chunk
        if len(current_chunk) + len(sentence) > max_chunk_size and current_chunk:
            chunks.append({
                'text': current_chunk.strip(),
                'page_number': page_number,
                'chunk_index': chunk_index,
            })
            chunk_index += 1
            current_chunk = sentence
        # If we have a good sized chunk and adding sentence exceeds target, save it
        elif len(current_chunk) > target_chunk_size and len(current_chunk) + len(sentence) > target_chunk_size:
            chunks.append({
                'text': current_chunk.strip(),
                'page_number': page_number,
                'chunk_index': chunk_index,
            })
            chunk_index += 1
            current_chunk = sentence
        else:
            # Add sentence to current chunk
            if current_chunk:
                current_chunk += " " + sentence
            else:
                current_chunk = sentence
    
    # Don't forget the last chunk
    if current_chunk.strip():
        chunks.append({
            'text': current_chunk.strip(),
            'page_number': page_number,
            'chunk_index': chunk_index,
        })
    
    return chunks

def create_embedding(text):
    """Create embedding for text using sentence transformer."""
    try:
        embedding = embedding_model.encode(text)
        return embedding.tolist()
    except Exception as e:
        print(f"Error creating embedding: {e}")
        return None

def process_pdf_file(file_path, customer_name):
    """Process a single PDF file and insert chunks into database."""
    print(f"\nProcessing: {os.path.basename(file_path)} for {customer_name}")
    
    # Check if this file is already processed
    file_name = os.path.basename(file_path)
    cursor.execute("""
        SELECT COUNT(*) FROM "CustomerSpecifications" 
        WHERE "fileName" = %s AND "customerName" = %s
    """, (file_name, customer_name))
    
    if cursor.fetchone()[0] > 0:
        print(f"Skipping {file_name}: Already processed for {customer_name}")
        return True
    
    # Upload file to S3
    file_id = upload_file_to_s3(file_path)
    if not file_id:
        return False
    
    # Extract text chunks
    chunks = extract_text_from_pdf(file_path)
    if not chunks:
        print(f"Warning: No text extracted from {file_name}")
        return False
    
    print(f"Extracted {len(chunks)} chunks from {len(set(c['page_number'] for c in chunks))} pages")
    
    # Process each chunk
    for chunk in chunks:
        try:
            # Create embedding
            embedding = create_embedding(chunk['text'])
            
            # Insert into database
            cursor.execute("""
                INSERT INTO "CustomerSpecifications" (
                    id, "createdAt", "customerName", "fileName", "fileId",
                    "chunkIndex", content, "pageNumber", embedding
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                str(uuid.uuid4()),
                datetime.now(),
                customer_name,
                file_name,
                file_id,
                chunk['chunk_index'],
                chunk['text'],
                chunk['page_number'],
                embedding
            ))
            
        except Exception as e:
            print(f"Error inserting chunk {chunk['chunk_index']}: {e}")
            conn.rollback()
            return False
    
    conn.commit()
    print(f"✓ Successfully processed {len(chunks)} chunks")
    return True

def get_customer_for_file(file_name):
    """Get customer name for a given file name."""
    for customer, mapped_files in CUSTOMER_FILE_MAPPING.items():
        if isinstance(mapped_files, list):
            if file_name in mapped_files:
                return customer
        elif mapped_files == file_name:
            return customer
    return None

def process_all_pdfs(specs_dir=None):
    """Process all PDF files in the specifications directory."""
    # Use provided specs_dir or default to 'specifications' relative to script location
    if specs_dir is None:
        specs_dir = os.path.join(os.path.dirname(__file__), 'specifications')
    else:
        specs_dir = os.path.abspath(specs_dir)
    
    if not os.path.exists(specs_dir):
        print(f"Error: Specifications directory not found at {specs_dir}")
        return
    
    pdf_files = [f for f in os.listdir(specs_dir) if f.endswith('.pdf')]
    
    if not pdf_files:
        print(f"No PDF files found in specifications directory: {specs_dir}")
        return
    
    print(f"Found {len(pdf_files)} PDF files to process in {specs_dir}")
    
    processed_count = 0
    error_count = 0
    skipped_count = 0
    
    for i, pdf_file in enumerate(pdf_files, 1):
        try:
            print(f"\n[{i}/{len(pdf_files)}] Processing: {pdf_file}")
            
            # Get customer for this file
            customer_name = get_customer_for_file(pdf_file)
            if not customer_name:
                print(f"Warning: No customer mapping found for {pdf_file}")
                skipped_count += 1
                continue
            
            file_path = os.path.join(specs_dir, pdf_file)
            
            if process_pdf_file(file_path, customer_name):
                processed_count += 1
                print(f"✓ Success")
            else:
                error_count += 1
                print(f"✗ Failed")
                
        except Exception as e:
            print(f"✗ Unexpected error processing {pdf_file}: {e}")
            import traceback
            traceback.print_exc()
            error_count += 1
            conn.rollback()
    
    print(f"\n{'='*50}")
    print(f"PROCESSING COMPLETE")
    print(f"{'='*50}")
    print(f"Total PDF files found: {len(pdf_files)}")
    print(f"Successfully processed: {processed_count}")
    print(f"Errors encountered: {error_count}")
    print(f"Skipped (no mapping): {skipped_count}")
    
    if len(pdf_files) > 0:
        success_rate = (processed_count / len(pdf_files) * 100)
        print(f"Success rate: {success_rate:.1f}%")
    
    if error_count > 0:
        print(f"\n⚠️  {error_count} files had errors. Check the logs above for details.")
    elif processed_count == 0:
        print(f"\n⚠️  No files were successfully processed.")
    else:
        print(f"\n🎉 Successfully processed {processed_count} files!")

def main():
    """Main entry point with argument parsing"""
    parser = argparse.ArgumentParser(
        description='Process PDF customer specifications and store in database with embeddings',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python pdf2db.py
  python pdf2db.py --specs-dir /path/to/specifications
  python pdf2db.py -s ./customer_specs
        """
    )
    
    parser.add_argument(
        '--specs-dir', '-s',
        type=str,
        help='Directory containing PDF specification files (default: ./specifications)',
        default=None
    )
    
    args = parser.parse_args()
    
    print("Starting PDF processing for Customer Specifications...")
    print(f"Specifications directory: {args.specs_dir or 'specifications (default)'}")
    print("This will:")
    print("1. Upload PDF files to S3")
    print("2. Extract text and create chunks")
    print("3. Generate embeddings for semantic search")
    print("4. Store everything in the database")
    print("-" * 50)
    
    process_all_pdfs(args.specs_dir)
    
    print("\nPDF processing complete.")

if __name__ == "__main__":
    main()
    cursor.close()
    conn.close()
