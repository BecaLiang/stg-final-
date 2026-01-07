import boto3
from dotenv import load_dotenv
import psycopg2
import os
import json
import uuid
import mimetypes
from datetime import datetime
import glob
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

# Default user email to look up
DEFAULT_USER_EMAIL = os.getenv("DEFAULT_USER_EMAIL", "bmuzuraimov@gmail.com")

def get_table_names():
    cursor.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
        AND table_type = 'BASE TABLE'
    """)
    return [row[0] for row in cursor.fetchall()]

def clean_value(value):
    """Convert None to empty string and clean strings"""
    if value is None:
        return ""
    if isinstance(value, (int, float)): # Ensure numbers are converted to string if clean_value is used for text fields
        return str(value)
    return str(value).strip()

def parse_date(date_str):
    """Parse date string to datetime object"""
    if not date_str or str(date_str).strip() == "":
        return None
    
    try:
        # Clean the date string first - handle full-width characters
        cleaned_date = str(date_str).strip()
        
        # Convert full-width characters to half-width
        full_width_chars = "０１２３４５６７８９／"
        half_width_chars = "0123456789/"
        translation_table = str.maketrans(full_width_chars, half_width_chars)
        cleaned_date = cleaned_date.translate(translation_table)
        
        # Handle date ranges - take the first date if there's a range
        if " / " in cleaned_date:
            cleaned_date = cleaned_date.split(" / ")[0].strip()
        elif "/" in cleaned_date and len(cleaned_date.split("/")) > 3:
            # Handle cases like "04/09/2023/29/09/2023" - take first complete date
            parts = cleaned_date.split("/")
            if len(parts) >= 3:
                cleaned_date = "/".join(parts[:3])
        
        # Try parsing different date formats
        date_formats = [
            "%Y-%m-%dT%H:%M:%S",  # ISO format with T separator
            "%Y-%m-%dT%H:%M:%S.%f",  # ISO format with T separator and microseconds
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
            "%m/%d/%Y",
            "%d/%m/%Y",
            "%Y.%m.%d",
            "%d.%m.%Y",
            # Adding format that might appear in Excel e.g. 45128 for 2023-07-22
            # This requires a different handling, typically using pandas or openpyxl date conversion
            # For now, sticking to string formats. If integer dates are common, this needs enhancement.
        ]
        
        for fmt in date_formats:
            try:
                return datetime.strptime(cleaned_date, fmt)
            except ValueError:
                continue
        
        print(f"Warning: Could not parse date: {date_str} (cleaned: {cleaned_date})")
        return None
    except Exception as e:
        print(f"Error parsing date {date_str}: {e}")
        return None

def upload_file_to_s3(file_path, is_image=True):
    """Upload file to S3 and return file ID and actual file name."""
    if not os.path.exists(file_path):
        print(f"Warning: File not found: {file_path}")
        return None, None
    
    base_file_name = os.path.basename(file_path)
    file_id = str(uuid.uuid4())
    
    if is_image:
        file_type = mimetypes.guess_type(file_path)[0] or 'image/png'
    else:
        file_type = mimetypes.guess_type(file_path)[0] or 'application/octet-stream'
        if base_file_name.endswith('.xlsx'):
            file_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

    # Extract file extension and include it in the S3 key to preserve it for downloads
    file_extension = os.path.splitext(base_file_name)[1]
    key = f"{file_id}{file_extension}"  # Include extension in S3 key
    
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
        return file_id, base_file_name
        
    except Exception as e:
        print(f"Error uploading {base_file_name}: {e}")
        conn.rollback()
        return None, None

def create_image_question_relations(question_id, image_files, images_dir, relation_type):
    """Create relations between question and images"""
    file_ids = []
    
    for image_file_name in image_files:
        if image_file_name:
            image_path = os.path.join(images_dir, image_file_name)
            file_id, _ = upload_file_to_s3(image_path, is_image=True) # Pass is_image=True
            if file_id:
                file_ids.append(file_id)
    
    for file_id in file_ids:
        try:
            if relation_type == "description":
                cursor.execute("""
                    INSERT INTO "_QuestionDescriptionImages" ("A", "B")
                    VALUES (%s, %s)
                """, (file_id, question_id))
            elif relation_type == "suggestion":
                cursor.execute("""
                    INSERT INTO "_QuestionSuggestionImages" ("A", "B")
                    VALUES (%s, %s)
                """, (file_id, question_id))
            elif relation_type == "customer_response":
                cursor.execute("""
                    INSERT INTO "_QuestionCustomerResponseImages" ("A", "B")
                    VALUES (%s, %s)
                """, (file_id, question_id))
            
            conn.commit()
            
        except Exception as e:
            print(f"Error creating image relation for file {file_id}: {e}")
            print(f"Question ID: {question_id}, File ID: {file_id}, Relation: {relation_type}")
            
            cursor.execute('SELECT id FROM "Question" WHERE id = %s', (question_id,))
            question_exists = cursor.fetchone()
            cursor.execute('SELECT id FROM "File" WHERE id = %s', (file_id,))
            file_exists = cursor.fetchone()
            
            print(f"Question exists: {question_exists is not None}, File exists: {file_exists is not None}")
            conn.rollback()

def create_image_question_relations_from_objects(question_id, image_objects, images_dir, relation_type):
    """Create relations between question and images from image objects in JSON"""
    for image_obj in image_objects:
        if image_obj and isinstance(image_obj, dict):
            image_file_name = image_obj.get('name')
            if image_file_name:
                image_path = os.path.join(images_dir, image_file_name)
                file_id, _ = upload_file_to_s3(image_path, is_image=True)
                if file_id:
                    try:
                        if relation_type == "description":
                            cursor.execute("""
                                INSERT INTO "_QuestionDescriptionImages" ("A", "B")
                                VALUES (%s, %s)
                            """, (file_id, question_id))
                        elif relation_type == "suggestion":
                            cursor.execute("""
                                INSERT INTO "_QuestionSuggestionImages" ("A", "B")
                                VALUES (%s, %s)
                            """, (file_id, question_id))
                        elif relation_type == "customer_response":
                            cursor.execute("""
                                INSERT INTO "_QuestionCustomerResponseImages" ("A", "B")
                                VALUES (%s, %s)
                            """, (file_id, question_id))
                        
                        conn.commit()
                        
                    except Exception as e:
                        print(f"Error creating image relation for file {file_id}: {e}")
                        print(f"Question ID: {question_id}, File ID: {file_id}, Relation: {relation_type}")
                        conn.rollback()

def process_json_file(json_file_path):
    """Process a single JSON file and insert data into database"""
    try:
        with open(json_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        json_dir = os.path.dirname(json_file_path)
        images_dir = os.path.join(json_dir, 'images')
        
        # Determine original Excel file name and path
        excel_basename_no_ext = os.path.basename(json_dir)

        print(f"Processing: {excel_basename_no_ext}")

        original_file_name = data.get('fileName')
        
        # Check if EQ with this fileName already exists
        file_name_to_check = clean_value(data.get('fileName', original_file_name))
        cursor.execute('SELECT id FROM "EQ" WHERE "fileName" = %s', (file_name_to_check,))
        existing_eq = cursor.fetchone()
        
        if existing_eq:
            print(f"Skipping {excel_basename_no_ext}: EQ with fileName '{file_name_to_check}' already exists (ID: {existing_eq[0]})")
            return True  # Return True to indicate successful processing (skipped)
        
        excel_path = os.path.join(json_dir, f"index.xlsx")

        if os.path.exists(excel_path):
            original_file_id, _ = upload_file_to_s3(excel_path, is_image=False)
            print(f"Uploaded original Excel: {excel_path} (ID: {original_file_id})")
        else:
            print(f"Warning: No Excel file found to upload")

        # The JSON structure has data at root level, not in metadata
        questions = data.get('questions', [])
        
        eq_id = str(uuid.uuid4())
        
        # Parse dates from the JSON
        stg_signature_date_parsed = parse_date(data.get('stgSignatureDate'))
        customer_signature_date_parsed = parse_date(data.get('customerSignatureDate'))

        # Ensure arrays are properly formatted from JSON
        def ensure_list(value):
            if isinstance(value, str):
                return [value.strip()] if value.strip() else []
            elif isinstance(value, list):
                return [str(v).strip() for v in value if str(v).strip()]
            return []

        # Get data directly from root level of JSON
        customer_pn_list = ensure_list(data.get('customerPN', []))
        factory_pn_list = ensure_list(data.get('factoryPN', []))
        stg_pn_list = ensure_list(data.get('stgPN', []))
        stg_signatures_list = ensure_list(data.get('stgSignatures', []))
        customer_signatures_list = ensure_list(data.get('customerSignatures', []))
            
        cursor.execute("""
            INSERT INTO "EQ" (
                id, "createdAt", "customerName", "engineerName",
                "customerPN", "factoryPN", "stgPN", 
                "baseMaterial", "solderMask", "viaPluggingType", "panelSize", "status",
                "stgSignatureDate", "stgSignatures", 
                "customerSignatureDate", "customerSignatures",
                "fileName", "originalFileId"
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            ) RETURNING id
        """, (
            eq_id,
            data.get('createdAt'),
            clean_value(data.get('customerName')),
            clean_value(data.get('engineerName')),
            customer_pn_list,
            factory_pn_list,
            stg_pn_list,
            clean_value(data.get('baseMaterial')),
            clean_value(data.get('solderMask')),
            clean_value(data.get('viaPluggingType')),
            clean_value(data.get('panelSize')),
            clean_value(data.get('status', 'Pending')),
            stg_signature_date_parsed,
            stg_signatures_list,
            customer_signature_date_parsed,
            customer_signatures_list,
            clean_value(data.get('fileName', original_file_name)),
            original_file_id
        ))
        
        conn.commit()
        
        for question_data in questions:
            question_id = str(uuid.uuid4())
            
            cursor.execute("""
                INSERT INTO "Question" (
                    id, "createdAt", no, description, suggestion,
                    "customerResponse", "EQId"
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s
                ) RETURNING id
            """, (
                question_id,
                question_data.get('createdAt'),
                clean_value(question_data.get('no')),
                clean_value(question_data.get('description')),
                clean_value(question_data.get('suggestion')),
                clean_value(question_data.get('customerResponse')),
                eq_id
            ))
            
            conn.commit()
            
            # Handle images - the JSON already contains image objects, not just filenames
            if os.path.exists(images_dir):
                # Process description images
                desc_images = question_data.get('descriptionImages', [])
                if desc_images:
                    create_image_question_relations_from_objects(question_id, desc_images, images_dir, "description")
                
                # Process suggestion images
                sugg_images = question_data.get('suggestionImages', [])
                if sugg_images:
                    create_image_question_relations_from_objects(question_id, sugg_images, images_dir, "suggestion")
                
                # Process customer response images
                resp_images = question_data.get('customerResponseImages', [])
                if resp_images:
                    create_image_question_relations_from_objects(question_id, resp_images, images_dir, "customer_response")
        
        print(f"Successfully processed {excel_basename_no_ext} with {len(questions)} questions")
        return True
        
    except Exception as e:
        print(f"Error processing {json_file_path}: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
        return False

def populate_database(input_dir=None):
    """Main function to populate database from JSON files"""
    tables = get_table_names()
    print(f"Available tables in database: {tables}")
    
    required_tables = ["EQ", "Question", "File", "User", 
                       "_QuestionDescriptionImages", "_QuestionSuggestionImages", "_QuestionCustomerResponseImages"]
    missing_tables = [t for t in required_tables if t not in tables]
    
    if missing_tables:
        # Check for Prisma style many-to-many table names like _FileToQuestion if direct names not found
        # This check is basic; Prisma's exact m2m naming can vary based on relation naming.
        # For now, we assume the script's explicit m2m table names are what Prisma generates or expects.
        print(f"Warning: Potentially missing tables: {missing_tables}. Ensure schema is migrated.")
        # The script will attempt to insert into these tables. If they don't exist, it will fail.
    
    # Use provided input_dir or default to 'processed_data' relative to script location
    if input_dir is None:
        output_dir = os.path.join(os.path.dirname(__file__), 'processed_data')
    else:
        output_dir = os.path.abspath(input_dir)
    
    if not os.path.exists(output_dir):
        print(f"Error: Input directory not found at {output_dir}")
        return
    
    json_files = glob.glob(os.path.join(output_dir, '*', 'index.json'))
    
    if not json_files:
        print(f"No index.json files found in subdirectories of {output_dir}")
        return
    
    print(f"Found {len(json_files)} JSON files to process in {output_dir}")
    
    processed_count = 0
    error_count = 0
    
    for i, json_file in enumerate(json_files, 1):
        try:
            print(f"\\n[{i}/{len(json_files)}] Processing file: {json_file}")
            
            if process_json_file(json_file):
                processed_count += 1
                print(f"✓ Success")
            else:
                error_count += 1
                print(f"✗ Failed")
            
            if i % 10 == 0:
                print(f"\\nProgress: {processed_count} processed, {error_count} errors ({i}/{len(json_files)} files)")
                
        except Exception as e:
            print(f"✗ Unexpected error processing {json_file}: {e}")
            import traceback
            traceback.print_exc()
            error_count += 1
            conn.rollback() # Ensure rollback on unexpected errors in the loop
    
    print(f"\\n{'='*50}")
    print(f"PROCESSING COMPLETE")
    print(f"{'='*50}")
    print(f"Total files found: {len(json_files)}")
    print(f"Successfully processed: {processed_count}")
    print(f"Errors encountered: {error_count}")
    if len(json_files) > 0 :
        print(f"Success rate: {(processed_count/len(json_files)*100):.1f}%")
    else:
        print(f"Success rate: N/A (no files to process)")

    
    if error_count > 0:
        print(f"\\n⚠️  {error_count} files had errors. Check the logs above for details.")
    elif processed_count == 0 and len(json_files) > 0:
        print(f"\\n⚠️  No files were successfully processed out of {len(json_files)} found.")
    elif len(json_files) == 0:
        print(f"\\nℹ️ No files found to process.")
    else:
        print(f"\\n🎉 All {processed_count} files processed successfully!")

def main():
    """Main entry point with argument parsing"""
    parser = argparse.ArgumentParser(
        description='Populate database from JSON files containing EQ data',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python json2db.py
  python json2db.py --input-dir /path/to/processed_data
  python json2db.py -i ./my_data_folder
        """
    )
    
    parser.add_argument(
        '--input-dir', '-i',
        type=str,
        help='Directory containing processed JSON files (default: ./processed_data)',
        default=None
    )
    
    args = parser.parse_args()
    
    print("Starting database population from JSON files...")
    print(f"Input directory: {args.input_dir or 'processed_data (default)'}")
    
    populate_database(args.input_dir)
    print("Database population complete.")

if __name__ == "__main__":
    main()
    
    cursor.close()
    conn.close()