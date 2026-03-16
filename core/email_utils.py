from django.core.mail import EmailMultiAlternatives, EmailMessage, get_connection
from django.template.loader import render_to_string
from django.template import TemplateDoesNotExist
from django.utils.html import strip_tags
from django.conf import settings
from email.mime.image import MIMEImage
import mimetypes
from smtplib import SMTPAuthenticationError, SMTPException
from django.core.mail.backends.smtp import EmailBackend
import threading

def send_email_html(subject, template_name, context, recipients, inline_images=None, attachments=None):
    html_body = render_to_string(template_name, context or {})
    text_body = ""
    try:
        txt_template = template_name.replace(".html", ".txt")
        text_body = render_to_string(txt_template, context or {})
    except TemplateDoesNotExist:
        text_body = strip_tags(html_body)
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "") or getattr(settings, "EMAIL_HOST_USER", "")
    to_list = recipients if isinstance(recipients, (list, tuple)) else [recipients]
    msg = EmailMultiAlternatives(subject, text_body, from_email, to_list)
    msg.attach_alternative(html_body, "text/html")
    if inline_images:
        for cid, path in (inline_images or {}).items():
            try:
                ctype, _ = mimetypes.guess_type(path)
                with open(path, "rb") as f:
                    data = f.read()
                image = MIMEImage(data, _subtype=(ctype.split("/")[-1] if ctype else "png"))
                image.add_header("Content-ID", f"<{cid}>")
                image.add_header("Content-Disposition", "inline")
                msg.attach(image)
            except Exception:
                continue
    # Attachments: list of tuples (filename, data_bytes, mimetype) or paths
    for att in (attachments or []):
        try:
            if isinstance(att, (list, tuple)) and len(att) >= 2:
                fname = att[0]
                data = att[1]
                mtype = att[2] if len(att) > 2 else mimetypes.guess_type(fname)[0] or "application/octet-stream"
                msg.attach(fname, data, mtype)
            elif isinstance(att, str):
                fname = att.split("/")[-1]
                ctype, _ = mimetypes.guess_type(att)
                with open(att, "rb") as f:
                    msg.attach(fname, f.read(), ctype or "application/octet-stream")
        except Exception:
            continue
    try:
        conn = get_connection(timeout=getattr(settings, "EMAIL_TIMEOUT", 10))
        conn.send_messages([msg])
    except (SMTPAuthenticationError, SMTPException, Exception):
        try:
            conn_ssl = EmailBackend(
                host=getattr(settings, "EMAIL_HOST", "smtp.gmail.com"),
                port=465,
                username=getattr(settings, "EMAIL_HOST_USER", ""),
                password=getattr(settings, "EMAIL_HOST_PASSWORD", ""),
                use_tls=False,
                use_ssl=True,
                timeout=getattr(settings, "EMAIL_TIMEOUT", 10),
            )
            conn_ssl.send_messages([msg])
        except Exception:
            if getattr(settings, "DEBUG", False):
                raise
def send_email_html_async(subject, template_name, context, recipients, inline_images=None, attachments=None):
    def _run():
        try:
            send_email_html(subject, template_name, context, recipients, inline_images, attachments)
        except Exception:
            pass
    t = threading.Thread(target=_run, daemon=True)
    t.start()

def send_email_text(subject, body, recipients):
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "") or getattr(settings, "EMAIL_HOST_USER", "")
    to_list = recipients if isinstance(recipients, (list, tuple)) else [recipients]
    msg = EmailMessage(subject, body, from_email, to_list)
    try:
        conn = get_connection(timeout=getattr(settings, "EMAIL_TIMEOUT", 10))
        conn.send_messages([msg])
    except (SMTPAuthenticationError, SMTPException, Exception):
        try:
            conn_ssl = EmailBackend(
                host=getattr(settings, "EMAIL_HOST", "smtp.gmail.com"),
                port=465,
                username=getattr(settings, "EMAIL_HOST_USER", ""),
                password=getattr(settings, "EMAIL_HOST_PASSWORD", ""),
                use_tls=False,
                use_ssl=True,
                timeout=getattr(settings, "EMAIL_TIMEOUT", 10),
            )
            conn_ssl.send_messages([msg])
        except Exception:
            if getattr(settings, "DEBUG", False):
                raise
