import logging
import os

# Kreiraj folder 'logs' ako ne postoji
os.makedirs("logs", exist_ok=True)

def setup_logger(name: str) -> logging.Logger:
    """Kreira i vraća konfigurirani logger koji piše u konzolu i u datoteku."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # Sprečava dupliciranje handlera ako se funkcija pozove više puta
    if not logger.handlers:
        # Format zapisa: [Datum Vrijeme] | Razina | Modul | Poruka
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname-8s)s | %(name)s:%(funcName)s:%(lineno)d - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )

        # 1. Handler za zapisivanje u datoteku (logs/app.log)
        file_handler = logging.FileHandler("logs/app.log", encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        # 2. Handler za ispis u terminal (opcionalno, da vidiš i tamo)
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger