export interface Role {
  key: string;
  name: string;
  color: string;
  stance: string;
  duty: string;
}

export interface CaseSummary {
  id: string;
  title: string;
  summary: string;
}

export interface AgentMessage {
  id: string;
  roleKey: string;
  name: string;
  color: string;
  text: string;
  done: boolean;
  round: number;
}

export interface Verdict {
  truth_hypothesis: string;
  evidence_chain: string[];
  doubts: string[];
  recommendation: string;
  disclaimer?: string;
}

export interface Contradiction {
  round?: number;
  issue: string;
  parties?: string[];
}

export type Status = "idle" | "running" | "awaiting_human" | "done";
