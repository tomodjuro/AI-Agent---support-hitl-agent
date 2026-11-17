import os
import imaplib
import smtplib
import email
from email.header import decode_header
from email.mime.text import MIMEText
from dotenv import load_dotenv
from logger import setup_logger

load_dotenv()

GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")



# Inicijalizacija loggera specifičnog za Gmail servis
logger = setup_logger("GmailService")

def check_and_fetch_emails():
    logger.info("Pokretanje provjere novih mailova s Gmaila...")
    
    try:
        # Primjer logiranja spajanja
        logger.debug("Spajanje na IMAP poslužitelj (imap.gmail.com)...")
        
        # ... tvoja logika za spajanje i pretraživanje mailova ...
        
        logger.info("Uspješno pronađeno i obrađeno novih [TEST-AI] poruka.")
        
    except Exception as e:
        # exc_info=True sprema cijeli traceback u logs/app.log
        logger.error(f"Greška tijekom komunikacije s Gmail API-jem: {e}", exc_info=True)
        raise e

def send_response_email(recipient, subject, body):
    logger.info(f"Slanje odgovora na email: {recipient} | Naslov: {subject}")
    
    try:
        # ... tvoja logika za slanje SMTP maila ...
        logger.info("Odgovor je uspješno poslan.")
        
    except Exception as e:
        logger.error(f"Neuspješno slanje emaila korisniku {recipient}: {e}", exc_info=True)
        raise e

def _decode_mime_words(s):
    """Dekodira naslove i imena pošiljatelja s hrvatskim znakovima (UTF-8)."""
    if not s:
        return ""
    decoded_fragments = decode_header(s)
    result = []
    for text, encoding in decoded_fragments:
        if isinstance(text, bytes):
            result.append(text.decode(encoding or "utf-8", errors="replace"))
        else:
            result.append(text)
    return "".join(result)

def fetch_test_emails():
    """Dohvaća nepročitane mailove koji u naslovu imaju '[TEST-AI]' putem IMAP-a."""
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        raise ValueError("Nedostaju GMAIL_USER ili GMAIL_APP_PASSWORD u .env datoteci!")

    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(GMAIL_USER, GMAIL_APP_PASSWORD)
    mail.select("inbox")

    # Sigurnosni filter: tražimo SAMO nepročitane mailove s [TEST-AI] u naslovu
    status, messages = mail.search(None, '(UNSEEN SUBJECT "[TEST-AI]")')
    email_ids = messages[0].split()

    emails = []
    for e_id in email_ids:
        # PEEK osigurava da mail ostane nepročitan dok ga ne obradimo
        _, msg_data = mail.fetch(e_id, "(BODY.PEEK[])")
        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        subject = _decode_mime_words(msg.get("Subject", "Bez naslova"))
        sender = _decode_mime_words(msg.get("From", ""))
        msg_id_header = msg.get("Message-ID", "")

        # Izvlačenje čistog teksta poruke
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))
                if content_type == "text/plain" and "attachment" not in content_disposition:
                    payload = part.get_payload(decode=True)
                    if payload:
                        body = payload.decode("utf-8", errors="replace")
                        break
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                body = payload.decode("utf-8", errors="replace")

        emails.append({
            "id": e_id.decode("utf-8"),          # IMAP ID za označavanje pročitanim
            "threadId": msg_id_header,          # Originalni Message-ID za reply thread
            "sender": sender,
            "subject": subject,
            "body": body.strip()
        })

    mail.logout()
    return emails

def send_reply_email(to_email: str, subject: str, body_text: str, original_msg_id: str = None, thread_id: str = None):
    """Šalje stvarni odgovor putem Gmail SMTP-a i označava dolazni mail kao pročitan."""
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        raise ValueError("Nedostaju GMAIL_USER ili GMAIL_APP_PASSWORD u .env datoteci!")

    reply_subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"

    msg = MIMEText(body_text, "plain", "utf-8")
    msg["From"] = GMAIL_USER
    msg["To"] = to_email
    msg["Subject"] = reply_subject
    
    if thread_id:
        msg["In-Reply-To"] = thread_id
        msg["References"] = thread_id

    # Slanje preko sigurnog SMTP SSL porta 465
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.send_message(msg)

    # Označi originalni dolazni mail kao pročitan (\Seen) u Inboxu
    if original_msg_id:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        mail.select("inbox")
        mail.store(original_msg_id.encode("utf-8"), "+FLAGS", "\\Seen")
        mail.logout()

    return True