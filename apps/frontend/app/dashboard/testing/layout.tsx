import { FullSandboxSuiteBar } from "./full-sandbox-suite-bar";

export default function TestingLayout({ children }: { children: React.ReactNode }) {
  // Keep the workspace single-layered: conceptually this remains "return children"
  // with one compact automation bar, not a second copy of the testing screen.
  return (
    <div className="space-y-5">
      <FullSandboxSuiteBar />
      {children}
    </div>
  );
}
