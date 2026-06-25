import { useI18n } from '../../../i18n-context'

interface LinkCard {
  href: string
  label: string
  desc: string
}

export function FinalLinksPanel() {
  const { t } = useI18n()

  const cards: LinkCard[] = [
    {
      href: '#/llm-extraction?tab=finalPromotion',
      label: t('dataCenter.openFinalPromotion'),
      desc: t('llm.workflow.boundaryPromotion'),
    },
    {
      href: '#/llm-extraction?tab=finalBrowser',
      label: t('dataCenter.openFinalBrowser'),
      desc: t('llm.workflow.boundaryFinal'),
    },
    {
      href: '#/llm-extraction?tab=finalExport',
      label: t('dataCenter.openFinalExport'),
      desc: t('dataCenter.boundaryExport'),
    },
    {
      href: '#/data-center?tab=final',
      label: t('dataCenter.finalKg'),
      desc: t('dataCenter.boundaryFinal'),
    },
    {
      href: '#/data-center?tab=exports',
      label: t('dataCenter.exports'),
      desc: t('dataCenter.boundaryExport'),
    },
    {
      href: '#/rule-validation',
      label: t('dataCenter.openValidation'),
      desc: t('llm.workflow.boundaryGovernance'),
    },
    {
      href: '#/human-review',
      label: t('dataCenter.openReview'),
      desc: t('llm.workflow.boundaryGovernance'),
    },
  ]

  return (
    <div className="llm-final-links-panel">
      <p className="llm-data-first-mode-note">{t('llm.dataFirst.dataFirstMode')}</p>
      <div className="llm-final-links-cards">
        {cards.map(card => (
          <div key={card.href} className="llm-final-link-card card">
            <div className="llm-final-link-card-title">{card.label}</div>
            <p className="llm-final-link-card-desc">{card.desc}</p>
            <a className="llm-btn llm-btn-primary" href={card.href}>{card.label}</a>
          </div>
        ))}
      </div>
    </div>
  )
}
