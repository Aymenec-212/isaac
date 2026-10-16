export const roleLabel: Record<string, string> = {
  owner: 'Propriétaire', admin: 'Administrateur', member: 'Membre',
};

export function auditLabel(action: string): string {
  const labels: Record<string, string> = {
    'workspace.created': 'Espace créé', 'workspace.renamed': 'Espace renommé',
    'invitation.created': 'Invitation créée', 'invitation.accepted': 'Invitation acceptée',
    'invitation.revoked': 'Invitation révoquée', 'membership.owner': 'Propriétaire désigné',
    'membership.admin': 'Administrateur désigné', 'membership.member': 'Rôle de membre attribué',
    'membership.revoked': 'Membre retiré', 'meeting.created': 'Réunion préparée',
    'meeting.access_granted': 'Accès à une réunion accordé',
    'meeting.access_revoked': 'Accès à une réunion retiré',
  };
  return labels[action] ?? 'Opération de l’espace';
}
