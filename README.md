# EQ Management System

A comprehensive Engineering Query (EQ) management platform for STARTEAM that streamlines the handling of customer specifications, engineering queries, and approval workflows.

## 🏗️ Architecture

The system consists of four main components:

- **Web Application**: React-based frontend built with Wasp framework
- **FastAPI Service**: Backend API for embeddings and Excel processing
- **PostgreSQL Database**: With pgvector extension for AI-powered search
- **Dataset Processing**: Scripts for converting Excel/PDF files to structured data

## 🚀 Quick Start

### Prerequisites

- Node.js 18+ and npm
- Python 3.9+
- Docker and Docker Compose
- PostgreSQL (or use the provided Docker setup)

### 1. Database Setup

```bash
cd db
docker build -t my_postgres_image .
docker-compose up -d
```

### 2. Web Application Setup

Install Wasp:
```bash
curl -sSL https://get.wasp-lang.dev/installer.sh | sh -s -- --version 0.15.0
```

Setup the web application:
```bash
cd web-app
wasp db start
```

Install pgvector in the PostgreSQL container:
```bash
docker exec -it my_postgres_container bash
apt-get update && apt-get install -y postgresql-16-pgvector
```

Migrate the database:
```bash
wasp db migrate-dev
```

Create environment files in `web-app` directory:

**`.env.server`**
```env
ADMIN_EMAILS=
AZURE_OPENAI_API_KEY=
AZURE_OPENAI_ENDPOINT=
AZURE_OPENAI_VERSION=
OPENAI_API_VERSION=
MAILGUN_API_KEY=
MAILGUN_DOMAIN=
SKIP_EMAIL_VERIFICATION_IN_DEV=true
FASTAPI_URL=http://localhost:8000
AWS_S3_IAM_ACCESS_KEY=
AWS_S3_IAM_SECRET_KEY=
AWS_S3_REGION=
AWS_S3_FILES_BUCKET=
```

**`.env.client`**
```env
REACT_APP_FASTAPI_URL=http://localhost:8000
```

Start the web application:
```bash
wasp start
```

### 3. FastAPI Service Setup

```bash
cd fastapi
python3.9 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Create `.env` file in `fastapi` directory:
```env
DATABASE_URL=postgresql://postgres:password@localhost:5432/eqmanagement
AWS_S3_ACCESS_KEY=your_aws_access_key
AWS_S3_SECRET_KEY=your_aws_secret_key
AWS_S3_REGION=your_aws_region
AWS_S3_BUCKET=your_s3_bucket_name
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:3001
```

Start the FastAPI service:
```bash
uvicorn main:app --reload
```

## 📊 Dataset Processing

The dataset processing scripts help convert existing data into the system:

### Excel to JSON
```bash
cd dataset
python excel2json.py --input-dir /path/to/excel/files --output-dir /path/to/output --outlier-dir /path/to/outliers
```

### JSON to Database
```bash
python json2db.py --input-dir /path/to/your/data
```

### PDF Specifications Processing
```bash
python pdf2db.py --specs-dir /path/to/your/specifications
```

## 🔗 API Documentation

Once running, access the API documentation at:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## 🌐 Application Access

- **Web Application**: http://localhost:3000
- **FastAPI Service**: http://localhost:8000
- **Database**: localhost:5432

## 📂 Key Features

- **EQ Management**: Create, edit, and track engineering queries
- **File Processing**: Automatic Excel and PDF processing with metadata extraction
- **AI-Powered Search**: Semantic search using embeddings
- **Customer Specifications**: PDF chunking and vector search
- **Approval Workflow**: Digital signatures and status tracking
- **Multi-language Support**: Built-in translation capabilities
- **File Storage**: AWS S3 integration for file management

## 🛠️ Production Deployment

### Docker Deployment

For production deployment, ensure you:

1. Update environment variables with production values
2. Configure proper SSL certificates
3. Set up secure database passwords
4. Configure AWS S3 buckets and IAM roles
5. Set up proper CORS origins for your domain

### Environment Variables

Ensure all required environment variables are set:
- Database connection strings
- AWS S3 credentials and bucket names
- OpenAI/Azure OpenAI API credentials
- Email service credentials (Mailgun)
- Proper CORS origins

## 📋 System Requirements

- **Memory**: Minimum 4GB RAM (8GB recommended)
- **Storage**: 10GB free space
- **Network**: Internet connection for AI services and email
- **Browser**: Modern browser with JavaScript enabled

## 🔧 Troubleshooting

### Common Issues

1. **Database Connection**: Ensure PostgreSQL is running and accessible
2. **pgvector Extension**: Install via `apt-get install postgresql-16-pgvector`
3. **Port Conflicts**: Check that ports 3000, 5432, and 8000 are available
4. **Environment Variables**: Verify all required environment variables are set

### Support

For technical issues, check the application logs:
- Web app logs: Available in the Wasp console
- FastAPI logs: Check `fastapi/app.log`
- Database logs: Use `docker logs my_postgres_container`

## 📄 License

This project is proprietary software developed for STARTEAM.
