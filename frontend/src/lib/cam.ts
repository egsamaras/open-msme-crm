export type CamSection = { key: string; title: string; body: string }
export type Cam = {
  sections: CamSection[]
  risk_grade: number
  ratios: Record<string, string | null>
  assumptions: Record<string, string>
}

export function gradeTone(grade: number): 'good' | 'warn' | 'bad' {
  return grade <= 3 ? 'good' : grade <= 6 ? 'warn' : 'bad'
}
