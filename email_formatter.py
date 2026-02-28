def format_email(analysis: dict, summaries: list[dict]) -> str:

    image_url = "https://i.imgur.com/caqEJI3.jpeg"
    header_image_html = f"""
    <tr><td style="padding:0; line-height:0;">
        <img src="{image_url}"
             width="680" style="display:block; width:100%; max-height:220px;
             object-fit:cover; object-position:center center;" />
    </td></tr>
    """

    def section_header(title: str, color: str = "#2c3e50") -> str:
        return f"""
        <tr><td style="padding: 30px 0 10px 0;">
            <h2 style="margin:0; color:{color}; font-size:18px;
                       border-bottom: 2px solid {color}; padding-bottom: 8px;">
                {title}
            </h2>
        </td></tr>
        """

    def author_line(first_author: str, last_author: str, group: str = "") -> str:
        first_author = first_author or ""
        last_author = last_author or ""
        group = group or ""
        group_badge = (
            f'<span style="background:#16a085; color:white; padding:1px 7px; '
            f'border-radius:8px; font-size:11px; margin-left:6px;">{group}</span>'
            if group else ""
        )
        if last_author and last_author != first_author:
            return (
                f'<div style="color:#7f8c8d; font-size:12px; margin-bottom:6px;">'
                f'{first_author} · · · {last_author}{group_badge}</div>'
            )
        return (
            f'<div style="color:#7f8c8d; font-size:12px; margin-bottom:6px;">'
            f'{first_author}{group_badge}</div>'
        )

    def paper_card(title, first_author, last_author, arxiv_id, note, dolphins="", group=""):
        title = title or "Untitled"
        first_author = first_author or ""
        last_author = last_author or ""
        arxiv_id = arxiv_id or ""
        note = note or ""
        dolphins = dolphins or ""
        group = group or ""
        url = f"https://arxiv.org/abs/{arxiv_id}"
        dolphin_html = (
            f'<span style="font-size:15px; margin-left:6px;">{dolphins}</span>'
            if dolphins else ""
        )
        return f"""
        <tr><td style="padding: 6px 0;">
            <div style="background:#f8f9fa; border-left:4px solid #3498db;
                        padding:12px 16px; border-radius:0 6px 6px 0;">
                <div style="margin-bottom:4px;">
                    <a href="{url}" style="color:#2c3e50; font-weight:bold;
                               text-decoration:none; font-size:14px;">{title}</a>
                    {dolphin_html}
                </div>
                {author_line(first_author, last_author, group)}
                <div style="color:#34495e; font-size:13px;">{note}</div>
            </div>
        </td></tr>
        """

    def must_see_card(paper):
        arxiv_id = paper.get("id", "")
        title = paper.get("title", "Untitled")
        first_author = paper.get("first_author", "")
        last_author = paper.get("last_author", "")
        group = paper.get("group", "")
        why = paper.get("why", "")
        url = f"https://arxiv.org/abs/{arxiv_id}"
        group_badge = (
            f'<span style="background:#e74c3c; color:white; padding:2px 8px; '
            f'border-radius:8px; font-size:12px; margin-left:8px;">{group}</span>'
            if group else ""
        )
        author_display = (
            f"{first_author} · · · {last_author}"
            if last_author and last_author != first_author
            else first_author
        )
        return f"""
        <tr><td style="padding: 0 0 20px 0;">
            <div style="background: linear-gradient(135deg, #1a1a2e, #0f3460);
                        border-radius:10px; padding:24px; color:white;">
                <div style="font-size:11px; letter-spacing:2px; color:#a8c6e8;
                            margin-bottom:10px;">TODAY'S MUST-SEE PAPER</div>
                <a href="{url}" style="color:white; font-weight:700; font-size:17px;
                           text-decoration:none; line-height:1.4; display:block;
                           margin-bottom:10px;">
                    {title}
                </a>
                <div style="color:#a8c6e8; font-size:12px; margin-bottom:12px;">
                    {author_display}{group_badge}
                </div>
                <div style="color:#e8f4f8; font-size:14px; line-height:1.6;
                            border-top:1px solid rgba(255,255,255,0.15);
                            padding-top:12px;">
                    {why}
                </div>
            </div>
        </td></tr>
        """

    def deep_dive_card(summary, first_author="", last_author="", group=""):
        arxiv_id = summary.get("id", "")
        title = summary.get("title", "Untitled")
        text_summary = summary.get("summary", "")
        why_it_matters = summary.get("why_it_matters", "")
        caveats = summary.get("caveats", "")
        first_author = first_author or ""
        last_author = last_author or ""
        group = group or ""
        url = f"https://arxiv.org/abs/{arxiv_id}"
        key_results = "".join(
            f'<li style="margin-bottom:4px;">{r}</li>'
            for r in summary.get("key_results", [])
        )
        caveats_html = (
            f'<div style="color:#95a5a6; font-size:12px; margin-top:8px;">'
            f'<strong>Caveats:</strong> {caveats}</div>'
            if caveats and caveats != "N/A" else ""
        )
        return f"""
        <tr><td style="padding: 10px 0;">
            <div style="background:#fff; border:1px solid #e0e0e0;
                        border-radius:8px; padding:20px;">
                <a href="{url}" style="color:#2980b9; font-weight:bold;
                           font-size:15px; text-decoration:none;">
                    {title}
                </a>
                <div style="margin:6px 0 12px 0;">
                    {author_line(first_author, last_author, group)}
                </div>
                <p style="color:#34495e; font-size:13px; line-height:1.6;
                          margin:0 0 8px 0;">
                    {text_summary}
                </p>
                <div style="margin:10px 0;">
                    <strong style="color:#2c3e50; font-size:12px;">KEY RESULTS</strong>
                    <ul style="margin:6px 0; padding-left:20px; color:#34495e;
                               font-size:13px;">
                        {key_results}
                    </ul>
                </div>
                <div style="background:#eaf4fb; padding:10px 12px;
                            border-radius:6px; margin-top:10px;">
                    <strong style="color:#2980b9; font-size:12px;">WHY IT MATTERS</strong>
                    <p style="margin:4px 0 0 0; color:#34495e; font-size:13px;">
                        {why_it_matters}
                    </p>
                </div>
                {caveats_html}
            </div>
        </td></tr>
        """

    def quirky_card(paper):
        arxiv_id = paper.get("id", "")
        title = paper.get("title", "Untitled")
        first_author = paper.get("first_author", "")
        last_author = paper.get("last_author", "")
        why_quirky = paper.get("why_quirky", "")
        url = f"https://arxiv.org/abs/{arxiv_id}"
        author_display = (
            f"{first_author} · · · {last_author}"
            if last_author and last_author != first_author
            else first_author
        )
        return f"""
        <tr><td style="padding: 6px 0;">
            <div style="background:#fef9e7; border-left:4px solid #f39c12;
                        padding:12px 16px; border-radius:0 6px 6px 0;">
                <a href="{url}" style="color:#2c3e50; font-weight:bold;
                           text-decoration:none; font-size:14px;">{title}</a>
                <div style="color:#95a5a6; font-size:12px; margin:4px 0 6px 0;">
                    {author_display}
                </div>
                <p style="color:#7f8c8d; font-size:13px; margin:0;">
                    {why_quirky}
                </p>
            </div>
        </td></tr>
        """

    from datetime import datetime
    today = datetime.now().strftime("%A, %B %d %Y")

    core_lookup = {p.get("id", ""): p for p in analysis.get("core_papers", [])}
    must_see = analysis.get("must_see", {})

    must_see_row = must_see_card(must_see) if must_see else ""

    deep_dive_rows = ""
    for s in summaries:
        sid = s.get("id", "")
        meta = core_lookup.get(sid) or {}
        first = meta.get("first_author", "")
        last = meta.get("last_author", "")
        group = meta.get("group", "")
        if sid == must_see.get("id", ""):
            first = must_see.get("first_author", first)
            last = must_see.get("last_author", last)
            group = must_see.get("group", group)
        deep_dive_rows += deep_dive_card(s, first, last, group)

    core_rows = ""
    for p in analysis.get("core_papers", []):
        core_rows += paper_card(
            p.get("title", "Untitled"),
            p.get("first_author", ""),
            p.get("last_author", ""),
            p.get("id", ""),
            p.get("relevance", ""),
            p.get("dolphins", ""),
            p.get("group", "")
        )

    foundations_rows = ""
    for p in analysis.get("foundations_papers", []):
        foundations_rows += paper_card(
            p.get("title", "Untitled"),
            p.get("first_author", ""),
            p.get("last_author", ""),
            p.get("id", ""),
            p.get("relevance", ""),
            group=p.get("group", "")
        )

    quirky_rows = ""
    for p in analysis.get("quirky_papers", []):
        quirky_rows += quirky_card(p)

    html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="margin:0; padding:0; background:#f0f2f5; font-family:
                 -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;">

        <table width="100%" cellpadding="0" cellspacing="0"
               style="background:#f0f2f5; padding:20px 0;">
        <tr><td align="center">
        <table width="680" cellpadding="0" cellspacing="0"
               style="background:white; border-radius:12px; overflow:hidden;
                      box-shadow:0 2px 8px rgba(0,0,0,0.08);">

            {header_image_html}

            <!-- Header -->
            <tr><td style="background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
                           padding:28px 40px;">
                <h1 style="margin:0; color:white; font-size:26px; font-weight:700;
                           letter-spacing:-0.5px;">✦ Delphinus</h1>
                <p style="margin:6px 0 0 0; color:#a8c6e8; font-size:14px;">
                    Daily arxiv digest — {today}
                </p>
            </td></tr>

            <!-- Body -->
            <tr><td style="padding:30px 40px 40px 40px;">
            <table width="100%" cellpadding="0" cellspacing="0">

                {must_see_row}
                {section_header("Deep Dives", "#c0392b")}
                {deep_dive_rows}
                {section_header("Your Research", "#2980b9")}
                {core_rows}
                {section_header("Quantum Foundations", "#8e44ad")}
                {foundations_rows}
                {section_header("Weird", "#e67e22")}
                {quirky_rows}

            </table>
            </td></tr>

            <!-- Footer -->
            <tr><td style="background:#f8f9fa; padding:20px 40px;
                           border-top:1px solid #e0e0e0; text-align:center;">
                <p style="margin:0; color:#95a5a6; font-size:12px;">
                    Delphinus · quant-ph + cond-mat.mes-hall · 🐬 tangential &nbsp;
                    🐬🐬 worth a look &nbsp; 🐬🐬🐬 must read
                </p>
            </td></tr>

        </table>
        </td></tr>
        </table>
    </body>
    </html>
    """

    return html