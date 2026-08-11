import { motion } from 'framer-motion'
import { Factory, WifiOff } from 'lucide-react'

interface Props {
  isDisconnected?: boolean
}

export function Header({ isDisconnected = false }: Props) {
  return (
    <motion.header
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="border-b border-border/40 bg-background/80 backdrop-blur-lg sticky top-0 z-50"
    >
      <div className="max-w-[1400px] mx-auto px-8 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl gradient-primary flex items-center justify-center shadow-glow-sm">
            <Factory className="w-[18px] h-[18px] text-white" />
          </div>
          <div>
            <h1 className="text-[15px] font-bold tracking-tight text-foreground leading-none">
              Dark Factory
            </h1>
            <p className="text-[10px] text-muted font-medium tracking-wide mt-0.5">
              Autonomous Software Delivery Platform
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {isDisconnected ? (
            <>
              <WifiOff className="w-3.5 h-3.5 text-warning" />
              <span className="text-[11px] text-warning font-medium">Disconnected</span>
            </>
          ) : (
            <>
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-success opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-success" />
              </span>
              <span className="text-[11px] text-muted-light font-medium">Live</span>
            </>
          )}
        </div>
      </div>
    </motion.header>
  )
}
