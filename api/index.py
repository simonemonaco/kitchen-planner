from app import create_app

# Vercel serverless entrypoint.
app = create_app(startup_checks=False)
