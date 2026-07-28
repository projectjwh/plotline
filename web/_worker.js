/**
 * Cloudflare Pages advanced-mode Worker.
 *
 * Puts HTTP Basic Auth in front of the entire static site (the explorer shell AND
 * explorer_data.json), so the deployment is reachable by link + password only —
 * not publicly indexable. Set the password once as a Pages secret:
 *
 *     npx wrangler pages secret put SITE_PASSWORD --project-name plotline
 *
 * The username is ignored — enter anything (e.g. "plotline") and the shared password.
 */
export default {
  async fetch(request, env) {
    const expected = env.SITE_PASSWORD;
    if (!expected) {
      return new Response("Site misconfigured: SITE_PASSWORD is not set.", { status: 500 });
    }

    const header = request.headers.get("Authorization") || "";
    let authorized = false;
    if (header.startsWith("Basic ")) {
      try {
        const decoded = atob(header.slice(6));
        const password = decoded.slice(decoded.indexOf(":") + 1);
        authorized = password.length === expected.length && password === expected;
      } catch (_) {
        authorized = false;
      }
    }

    if (!authorized) {
      return new Response("Authentication required.", {
        status: 401,
        headers: {
          "WWW-Authenticate": 'Basic realm="Plotline", charset="UTF-8"',
          "Cache-Control": "no-store",
          "X-Robots-Tag": "noindex, nofollow",
        },
      });
    }

    // Authorized: serve the static asset (shell or data JSON) and keep it out of indexes.
    const response = await env.ASSETS.fetch(request);
    const out = new Response(response.body, response);
    out.headers.set("X-Robots-Tag", "noindex, nofollow");
    return out;
  },
};
