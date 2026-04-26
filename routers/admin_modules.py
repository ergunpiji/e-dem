"""
Admin Modüller — sistem modüllerinin durumunu/aktivasyonunu yönetir.
v1: placeholder kart görünümü; modüllerin durumu ve gelecek aktivasyon notu.
v2'de E-Fatura için wizard (mali mühür + entegratör seçimi) açılır.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from auth import require_admin
from models import User
from templates_config import templates


router = APIRouter(prefix="/admin/modules", tags=["admin_modules"])


# Modül kataloğu — şu an sadece bilgilendirme için
MODULES = [
    {
        "key": "einvoice",
        "name": "E-Fatura / E-Arşiv",
        "icon": "bi-receipt-cutoff",
        "color": "#1A3A5C",
        "status": "inactive",        # inactive | configuring | active
        "status_label": "Pasif",
        "description": (
            "Türkiye e-Fatura/e-Arşiv entegrasyonu — webapp üzerinden direkt "
            "GİB'e fatura kesme ve gelen e-faturaları otomatik sisteme çekme."
        ),
        "blocked_reason": (
            "Mali mühür sertifikası ve özel entegratör (İzibiz/Paraşüt/Faturaport) "
            "seçimi tamamlandıktan sonra aktive edilebilir."
        ),
        "next_steps": [
            "KamuSM'den mali mühür başvurusu (5–10 iş günü, ~1.500–3.500 TL)",
            "İzibiz ve Paraşüt'ten teklif alın (Logo müşterisi olduğunuz için İzibiz öncelikli)",
            "Seçilen entegratörle GİB e-Fatura mükellefiyet başvurusu",
            "Sertifika + entegratör onayı geldiğinde 'Aktive Et' butonu açılacak",
        ],
        "scope": [
            "Giden: kesilen faturalar e-Fatura (B2B) veya e-Arşiv (B2C) olarak GİB'e gönderilir",
            "Gelen: tedarikçilerin kestiği e-faturalar otomatik webapp'e düşer (inbox)",
            "Gönderilen faturanın PDF'i + iptal akışı + status takibi",
            "Müşteri/tedarikçi e-Fatura mükellefi otomatik kontrol",
        ],
    },
    {
        "key": "edefter",
        "name": "E-Defter",
        "icon": "bi-journal-text",
        "color": "#1E5F8C",
        "status": "planned",
        "status_label": "Planlandı",
        "description": "Aylık/yıllık yevmiye + büyük defter elektronik gönderimi.",
        "blocked_reason": "E-Fatura modülü aktive edildikten sonra planlanacak.",
        "next_steps": [],
        "scope": [],
    },
    {
        "key": "tax_reports",
        "name": "Vergi Raporları (KDV / BA-BS)",
        "icon": "bi-file-earmark-bar-graph",
        "color": "#16a34a",
        "status": "planned",
        "status_label": "Planlandı",
        "description": (
            "KDV1/KDV2 özet raporu, BA/BS otomatik üretimi, geçici vergi tahmini, "
            "yıllık kâr/zarar projeksiyonu."
        ),
        "blocked_reason": "E-Fatura modülünden veri toplanacağı için onun aktivasyonunu bekliyor.",
        "next_steps": [],
        "scope": [],
    },
]


@router.get("", response_class=HTMLResponse, name="admin_modules_list")
async def modules_list(
    request: Request,
    current_user: User = Depends(require_admin),
):
    return templates.TemplateResponse(
        "admin_modules/list.html",
        {
            "request": request,
            "current_user": current_user,
            "page_title": "Modüller",
            "modules": MODULES,
        },
    )


@router.get("/{module_key}", response_class=HTMLResponse, name="admin_module_detail")
async def module_detail(
    module_key: str,
    request: Request,
    current_user: User = Depends(require_admin),
):
    mod = next((m for m in MODULES if m["key"] == module_key), None)
    if not mod:
        return templates.TemplateResponse(
            "admin_modules/list.html",
            {
                "request": request,
                "current_user": current_user,
                "page_title": "Modüller",
                "modules": MODULES,
                "error": f"Modül bulunamadı: {module_key}",
            },
        )
    return templates.TemplateResponse(
        "admin_modules/detail.html",
        {
            "request": request,
            "current_user": current_user,
            "page_title": mod["name"],
            "module": mod,
        },
    )
