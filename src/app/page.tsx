import Link from "next/link";

const setupChecklist = [
  "Run npm run setup to install dependencies and create .env.local.",
  "Fill out .env.local with your Supabase, Stripe, and email credentials.",
  "Run npm run dev and confirm the app loads at http://localhost:3000.",
  "Use npm run check to run lint and typecheck before opening a PR.",
];

const quickLinks = [
  {
    href: "/donate?church_id=EGQR-123",
    title: "Donation flow",
    description: "Open the donation experience with a sample church id.",
  },
  {
    href: "/admin/onboarding",
    title: "Church onboarding",
    description: "Create and configure church records for testing.",
  },
  {
    href: "/api/health",
    title: "Health check API",
    description: "Confirm runtime configuration is loaded and healthy.",
  },
];

export default function Home() {
  return (
    <main className="min-h-screen bg-zinc-950 text-zinc-100">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-10 px-6 py-16 md:px-10">
        <header className="space-y-4">
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-zinc-400">
            New project starter
          </p>
          <h1 className="text-4xl font-semibold tracking-tight md:text-5xl">
            EasyGiveQR web workspace
          </h1>
          <p className="max-w-3xl text-base text-zinc-300 md:text-lg">
            This repository is ready for building donation checkout, onboarding,
            and admin tools. Start by configuring environment variables and
            validating the core routes.
          </p>
        </header>

        <section className="rounded-2xl border border-zinc-800 bg-zinc-900/60 p-6 shadow-sm">
          <h2 className="mb-4 text-xl font-semibold text-zinc-100">
            Quick setup checklist
          </h2>
          <ol className="space-y-3 text-sm text-zinc-300 md:text-base">
            {setupChecklist.map((item, index) => (
              <li key={item} className="flex gap-3">
                <span className="mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-zinc-700 text-xs font-semibold text-zinc-100">
                  {index + 1}
                </span>
                <span>{item}</span>
              </li>
            ))}
          </ol>
        </section>

        <section className="grid gap-4 md:grid-cols-3">
          {quickLinks.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-5 transition-colors hover:border-zinc-600 hover:bg-zinc-900"
            >
              <h3 className="text-lg font-semibold">{link.title}</h3>
              <p className="mt-2 text-sm text-zinc-300">{link.description}</p>
            </Link>
          ))}
        </section>
      </div>
    </main>
  );
}
