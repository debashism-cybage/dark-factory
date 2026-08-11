import { motion } from 'framer-motion'
import { Shield, Bug, TestTube, Rocket, CheckCircle, Clock, Loader } from 'lucide-react'

interface QualityGate {
  value: string
  status: string
  subtitle: string
}

interface QualityData {
  coverage?: QualityGate
  security?: QualityGate
  tests?: QualityGate
  deployment?: QualityGate
}

interface Props {
  quality?: QualityData
}

export function QualityCards({ quality }: Props) {
  const items = buildItems(quality)

  return (
    <motion.section
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay: 0.35 }}
    >
      <p className="section-title mb-4">Quality Gates</p>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {items.map((item, i) => (
          <QualityCard key={item.label} item={item} index={i} />
        ))}
      </div>
    </motion.section>
  )
}

interface QualityItem {
  icon: React.ReactNode
  label: string
  value: string
  subtitle: string
  status: 'passed' | 'running' | 'pending' | 'failed'
}

function buildItems(quality?: QualityData): QualityItem[] {
  const cov = quality?.coverage
  const sec = quality?.security
  const tst = quality?.tests
  const dep = quality?.deployment

  return [
    {
      icon: <TestTube className="w-7 h-7" />,
      label: 'Coverage',
      value: cov?.value || 'Pending',
      subtitle: cov?.subtitle || 'Awaiting validation',
      status: mapStatus(cov?.status),
    },
    {
      icon: <Shield className="w-7 h-7" />,
      label: 'Security',
      value: sec?.value || 'Pending',
      subtitle: sec?.subtitle || 'Awaiting scan',
      status: mapStatus(sec?.status),
    },
    {
      icon: <Bug className="w-7 h-7" />,
      label: 'Tests',
      value: tst?.value || 'Pending',
      subtitle: tst?.subtitle || 'Awaiting tests',
      status: mapStatus(tst?.status),
    },
    {
      icon: <Rocket className="w-7 h-7" />,
      label: 'Deployment',
      value: dep?.value || 'Pending',
      subtitle: dep?.subtitle || 'Awaiting deployment',
      status: mapStatus(dep?.status),
    },
  ]
}

function mapStatus(status?: string): 'passed' | 'running' | 'pending' | 'failed' {
  if (status === 'passed') return 'passed'
  if (status === 'failed') return 'failed'
  if (status === 'running') return 'running'
  return 'pending'
}

function QualityCard({ item, index }: { item: QualityItem; index: number }) {
  const colorClass = item.status === 'passed'
    ? 'text-success'
    : item.status === 'failed'
      ? 'text-error'
      : item.status === 'running'
        ? 'text-primary-light'
        : 'text-muted'

  const bgClass = item.status === 'passed'
    ? 'bg-success/[0.06]'
    : item.status === 'failed'
      ? 'bg-error/[0.06]'
      : item.status === 'running'
        ? 'bg-primary/[0.06]'
        : 'bg-border/30'

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.08 * index }}
      className="card-hover p-5 text-center"
    >
      <div className={`inline-flex p-3.5 rounded-2xl ${bgClass} ${colorClass} mb-3`}>
        {item.icon}
      </div>
      <p className={`text-2xl font-bold ${colorClass} mb-0.5`}>{item.value}</p>
      <p className="text-xs font-medium text-foreground mb-1">{item.subtitle}</p>
      {item.status === 'passed' && (
        <div className="flex items-center justify-center gap-1 mt-2.5">
          <CheckCircle className="w-3 h-3 text-success/60" />
          <span className="text-[9px] text-success/60 font-medium uppercase tracking-wider">Passed</span>
        </div>
      )}
      {item.status === 'pending' && (
        <div className="flex items-center justify-center gap-1 mt-2.5">
          <Clock className="w-3 h-3 text-muted/40" />
          <span className="text-[9px] text-muted/40 font-medium uppercase tracking-wider">Pending</span>
        </div>
      )}
      {item.status === 'running' && (
        <div className="flex items-center justify-center gap-1 mt-2.5">
          <Loader className="w-3 h-3 text-primary-light/60 animate-spin" />
          <span className="text-[9px] text-primary-light/60 font-medium uppercase tracking-wider">Running</span>
        </div>
      )}
    </motion.div>
  )
}
