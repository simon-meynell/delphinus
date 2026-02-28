import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.audio import MIMEAudio
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

def send_digest(html: str, podcast_path: str = None):
    """
    Sends the formatted HTML digest to your inbox.
    Optionally attaches a podcast MP3 if podcast_path is provided.
    """
    sender = os.getenv("EMAIL_ADDRESS")
    password = os.getenv("EMAIL_APP_PASSWORD")
    recipient = [r.strip() for r in os.getenv("EMAIL_TO", "").split(",")]

    today = datetime.now().strftime("%B %d, %Y")
    subject = f"✦ Delphinus — {today}"

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipient)

    # HTML body
    msg.attach(MIMEText(html, "html"))

    # Attach podcast if available
    if podcast_path and os.path.exists(podcast_path):
        print(f"Attaching podcast: {podcast_path}")
        with open(podcast_path, "rb") as f:
            audio = MIMEAudio(f.read(), _subtype="mpeg")
        audio.add_header(
            "Content-Disposition",
            "attachment",
            filename=os.path.basename(podcast_path)
        )
        msg.attach(audio)

    print("Sending email...")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, recipient, msg.as_string())
    print("Email sent!")