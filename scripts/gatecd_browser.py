"""Shared Playwright actions for the real G-0C/G-0D closure assays."""


def mount_ui(harness, project, viewport=None):
    page = harness.page
    page.set_viewport_size(viewport or {"width": 1100, "height": 800})
    page.evaluate(
        """async ({project, stylesheet}) => {
        app.destroy();
        document.body.replaceChildren();
        if (!document.querySelector('link[data-f9-release-style]')) {
            const link = document.createElement('link'); link.rel='stylesheet';
            link.href=stylesheet; link.dataset.f9ReleaseStyle='true';
            await new Promise((resolve,reject)=>{link.onload=resolve;link.onerror=reject;document.head.append(link)});
        }
        const root=document.body.appendChild(document.createElement('div'));
        const {mountControlLabApp}=await import('/app/main.js');
        globalThis.app=mountControlLabApp(root,{project_id:project});
        await app.client.init();
    }""",
        {"project": project, "stylesheet": harness.origin + "/app/styles.css"},
    )
    return page


def wait_committed(page):
    page.wait_for_function("""() => {
        const w=app.shell.getLqrWorkspace();
        return w.getCommittedSnapshot() !== null && !w.isPendingCommit() && !w.getPreviewState().active;
    }""")


def stored_project(page):
    return page.evaluate("""async () => {
        const w=app.shell.getLqrWorkspace();
        return app.client.exportProject(w.getProjectId());
    }""")


def without_export_time(snapshot):
    return {k: v for k, v in snapshot.items() if k != "exported_at"}
