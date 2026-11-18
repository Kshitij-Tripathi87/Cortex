import { Metadata } from 'next';
import Link from 'next/link';

export const metadata: Metadata = {
  title: 'Security | Cortex',
  description:
    'How Cortex protects your data today: sign-in, separation between organizations, approvals, the activity log, and what is not available yet.',
};

/*
 * Every statement on this page describes behaviour that exists in the code and
 * is covered by a test. Before changing a sentence, check the place it comes
 * from:
 *
 *   sign-in rules, limits, reset links   backend/app/api/v1/auth.py
 *   workspace check on each request      backend/app/infrastructure/security.py
 *   roles                                backend/app/modules/nexus_spine/p0_migration/authz.py
 *   decision stages                      backend/app/modules/nexus_spine/governance/lifecycle.py
 *   what the language model receives     backend/app/modules/nexus_spine/p0_migration/llm_adapter.py
 *   activity log                         backend/app/modules/audit/
 *
 * The page used to promise single sign-on, mutual TLS, AES-256 with
 * customer-managed keys, dedicated infrastructure per customer and a
 * tamper-evident log exported to monitoring tools. None of those exist. A
 * capability belongs under "Not available yet" until it does.
 */

const DECISION_STAGES = [
  'Proposed',
  'Simulated',
  'Policy checked',
  'Awaiting approval',
  'Approved',
  'Authorized',
  'Executing',
  'Executed',
  'Outcome recorded',
];

const NOT_AVAILABLE = [
  'Single sign-on through your identity provider (SAML or OIDC), and a second sign-in factor.',
  'Adding colleagues to your workspace. The server already checks a role on every request, but each signup creates one admin.',
  'Cancelling a sign-in before its 60 minutes are over.',
  'Encryption keys that you manage yourself.',
  'An activity log sealed against later changes, and export of the log to monitoring tools.',
  'Servers or databases reserved for one customer.',
];

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="text-2xl font-medium mb-6 pb-2 border-b border-[#262626]">{title}</h2>
      <div className="space-y-4 text-[#B3B3B3] leading-relaxed">{children}</div>
    </section>
  );
}

function Points({ items }: { items: React.ReactNode[] }) {
  return (
    <ul className="space-y-3">
      {items.map((item, index) => (
        <li key={index} className="flex gap-3">
          <span aria-hidden="true" className="mt-[0.7em] h-1 w-1 shrink-0 bg-[#10B981]" />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

export default function SecurityPage() {
  return (
    <div className="min-h-screen bg-[#0A0A0A] text-white" data-testid="security-page">
      <main className="max-w-[1440px] mx-auto px-6 md:px-12 py-24 md:py-32">
        <div className="max-w-4xl">
          <div className="font-mono text-[#10B981] text-xs uppercase tracking-widest mb-6 border-l-2 border-[#10B981] pl-4">
            Cortex / Security
          </div>
          <h1 className="text-4xl md:text-5xl font-medium tracking-tight mb-8">
            How Cortex protects your data
          </h1>

          <p className="text-lg text-[#E5E5E5] mb-16 max-w-3xl leading-relaxed">
            This page describes what the software does today and what it does not do yet. It is a
            description of the product, not a certification.
          </p>

          <div className="space-y-16">
            <Section title="Signing in">
              <Points
                items={[
                  'You sign in with an email address and a password of at least 10 characters that contains a letter and a digit.',
                  'Passwords are stored as salted bcrypt hashes. Nobody at Cortex can read your password.',
                  'A sign-in lasts 60 minutes. Signing out removes it from your browser. The server keeps no list of cancelled sign-ins, so a copied sign-in stays valid until its 60 minutes are over.',
                  'After 10 wrong passwords within 15 minutes for one email address from one network address, further attempts are refused for up to 15 minutes.',
                  'A forgotten password is reset through a link that a Cortex team member sends after you ask for one. The link works once and expires, normally after 24 hours. No reset email is sent automatically.',
                ]}
              />
            </Section>

            <Section title="Keeping organizations apart">
              <Points
                items={[
                  'Each signup creates its own organization with its own workspace.',
                  'Every record and every uploaded file belongs to one workspace. On each request the server compares the workspace asked for with the one in your sign-in and refuses any other.',
                  'All organizations share one database and one file store. The separation is enforced by the application on every request, not by separate servers.',
                ]}
              />
            </Section>

            <Section title="Roles">
              <Points
                items={[
                  'The server checks a role on every request. Viewers read. Analysts also run simulations and record risks. Operators and admins also create, approve and close decisions.',
                  'Today the person who signs up is the admin of the organization, and colleagues cannot be added yet.',
                ]}
              />
            </Section>

            <Section title="Decisions need a person">
              <div className="bg-[#111111] border border-[#262626] p-6 md:p-8">
                <h3 className="text-sm font-mono text-[#999999] mb-5 uppercase tracking-wider">
                  Stages of a decision
                </h3>
                <ol
                  className="flex flex-wrap items-center gap-x-2 gap-y-3 font-mono text-sm text-[#E5E5E5]"
                  data-testid="security-decision-stages"
                >
                  {DECISION_STAGES.map((stage, index) => (
                    <li key={stage} className="flex items-center gap-2">
                      <span
                        className={`bg-[#1A1A1A] border border-[#262626] px-3 py-2 ${
                          stage === 'Approved' ? 'text-[#10B981]' : ''
                        }`}
                      >
                        {stage}
                      </span>
                      {index < DECISION_STAGES.length - 1 && (
                        <span aria-hidden="true" className="text-[#666666]">
                          →
                        </span>
                      )}
                    </li>
                  ))}
                </ol>
              </div>
              <Points
                items={[
                  'The server enforces this order. A decision cannot be approved before it has been put up for approval, and cannot be marked executed before it is approved.',
                  'Approving needs the operator or admin role. Each step is stored with who made it, when, and the reason given.',
                  'Cortex does not act on your other systems. "Executed" is a stage of the record inside Cortex. The connectors to ERP, warehouse, transport and procurement systems in this release are simulations and send nothing.',
                ]}
              />
            </Section>

            <Section title="Your uploaded files">
              <Points
                items={[
                  'An uploaded file is not part of your data until a person has reviewed its values and published it.',
                  'The list of your uploads shows where each file stands, and every published record keeps the name of the file it came from.',
                ]}
              />
            </Section>

            <Section title="Questions you ask">
              <Points
                items={[
                  'Answers are worded by a language-model service. The question you type and the records found for it are sent to that service.',
                  'The model can look up your records and run a what-if simulation or a forecast. It cannot change your published data, approve a decision or execute one.',
                  'Each answered question is noted in the activity log with who asked and which lookups ran.',
                ]}
              />
              <p>
                Which model service receives your questions depends on your deployment.{' '}
                <Link href="/contact?topic=security#write" className="text-white underline underline-offset-4 hover:text-[#10B981]">
                  Ask us
                </Link>{' '}
                before you type anything you would not send to a third party.
              </p>
            </Section>

            <Section title="Activity log">
              <Points
                items={[
                  'Recorded: signups, sign-ins, sign-outs, password changes, reset requests and completed resets; uploads; each review of an uploaded value; each publication; each question that was answered; attempts to move a decision that the server refused as out of order.',
                  'Everyone in a workspace can read its log under Operations, Audit events.',
                  'The application only adds entries. It never changes or deletes them. The log is kept in the same database as your data and is not sealed, so it is not proof against someone with direct access to the database.',
                ]}
              />
            </Section>

            <Section title="Encryption and hosting">
              <Points
                items={[
                  'The API tells browsers that reach it over HTTPS to keep using HTTPS for a year.',
                  'Whether stored data is encrypted on disk, where it is hosted and how it is backed up depend on how a deployment is set up, not on the software.',
                ]}
              />
              <p>
                <Link href="/contact?topic=security#write" className="text-white underline underline-offset-4 hover:text-[#10B981]">
                  Ask us for these details
                </Link>{' '}
                of your deployment before you upload sensitive data.
              </p>
            </Section>
          </div>

          <div className="mt-20 p-8 border border-[#262626] bg-[#111111]" data-testid="security-not-available">
            <h2 className="text-xl font-medium mb-2">Not available yet</h2>
            <p className="text-[#999999] mb-6">
              If your organization requires one of these, tell us before you start.
            </p>
            <Points items={NOT_AVAILABLE} />
          </div>

          <div className="mt-8 p-8 border border-[#262626] bg-[#111111]">
            <h2 className="text-xl font-medium mb-4">Report a security problem</h2>
            <p className="text-[#999999] mb-6">
              If you have found a weakness in Cortex, report it through the form below. For any other
              question about security, write to us.
            </p>
            <div className="flex flex-wrap gap-3">
              <Link
                href="/security/report-vulnerability"
                className="inline-block bg-[#1A1A1A] hover:bg-[#262626] border border-[#262626] text-white px-6 py-3 font-mono text-sm transition-colors"
              >
                Report a vulnerability →
              </Link>
              <Link
                href="/contact?topic=security#write"
                className="inline-block border border-[#262626] hover:bg-[#1A1A1A] text-white px-6 py-3 font-mono text-sm transition-colors"
              >
                Ask a security question →
              </Link>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
