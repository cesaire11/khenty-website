# KHENTY — Gestion privée, version de préparation

## Ce qui fonctionne dans les tests

- Connexion administrateur unique, cookie HttpOnly/Secure/SameSite, expiration après 8 heures, déconnexion et révocation au redémarrage.
- Protection des écritures par origine exacte et jeton CSRF ; limitation persistante des tentatives de connexion (10 par 15 minutes pour le service).
- Catalogue, fournisseurs, contrôle documenté, prix distincts XAF et SAR, validation des échantillons et du logo.
- Prix SAR stockés en halalas, XAF en unités entières. Aucune commission supplémentaire appliquée automatiquement ; la marge cible de 30 % doit être comprise dans le prix saisi.
- Stocks KHENTY : mouvements transactionnels, motif et historique ; stock négatif interdit. Stock fournisseur distinct et confirmé manuellement.
- Dossiers internes : préparation, devis réellement envoyé, annulation. Aucune preuve de paiement, facture fiscale, réservation, expédition ou vente n'est fabriquée.
- Les 8 produits initiaux sont des concepts, sans prix, sans fournisseur et sans stock confirmé.
- Contrôle de version des modifications produit pour éviter d'écraser une modification concurrente.

## Mise en service proposée — ne pas appliquer sans accord sur le coût

Conserver la vitrine statique `khenty-website` et créer un service séparé `khenty-gestion`, dans le workspace déjà confirmé. Région proposée : Francfort. Configuration minimale : instance payante de 512 Mo (Starter/0.5c-512mb selon le catalogue Render), disque persistant de 1 Go monté sur `/var/data`, une seule instance et un seul worker Gunicorn.

- Dépôt : `https://github.com/cesaire11/khenty-website`, branche `main`.
- Build : `pip install -r backend/requirements.txt`.
- Start : `gunicorn --chdir backend 'app:create_app()' --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 30`.
- Health check : `/health`.
- `KHENTY_DB=/var/data/khenty.sqlite3`.
- `PUBLIC_ORIGIN` : origine HTTPS exacte attribuée au nouveau service, sans chemin.
- `ADMIN_PASSWORD` : secret fort d'au moins 20 caractères, à définir dans les variables protégées Render ; ne jamais le committer ni le transmettre dans le chat.

L'API refuse de démarrer sans ces paramètres. Ne pas utiliser un service gratuit à disque éphémère pour de vraies données. Ne pas multiplier les workers : leur initialisation révoque les sessions.

Après mise en service, vérifier `/health`, ouvrir `/admin`, faire définir ou saisir le mot de passe par le propriétaire et tester un enregistrement non commercial. Vérifier sa persistance après redémarrage. Ensuite seulement, remplacer `null` par l'origine HTTPS du service dans `storefront-config.json`. La vitrine lira le catalogue public via l'API ; les données privées resteront derrière la connexion. Seule la vitrine `https://khenty-website.onrender.com` est autorisée à lire l'API publique par CORS. Les écritures sont réservées à l'origine du service de gestion.

## Coût estimé, à confirmer dans Render avant création

Tarifs affichés dans la page de prix officielle consultée le 4 novembre 2026 : service 512 Mo à 7 USD/mois et disque à 0,25 USD/Go/mois, soit **environ 7,25 USD/mois de ressources supplémentaires** pour 1 Go. Ce n'est pas un plafond de facturation : taxes, formule workspace éventuelle, dépassements de trafic/builds, sauvegardes externes et autres ressources sont exclus. Aucun service payant n'a été créé dans cette étape.

Sources : https://render.com/pricing et https://render.com/docs/disks.

## Sauvegarde et limites

SQLite convient à ce premier espace interne mono-instance. Le disque rend la base persistante mais n'est pas une sauvegarde indépendante. Avant de saisir des informations opérationnelles, définir une sauvegarde cohérente via l'API `sqlite3.Connection.backup`, vers un stockage séparé, et tester la restauration. L'export JSON de l'interface est partiel et ne remplace pas cette sauvegarde. Les déploiements d'un service avec disque peuvent interrompre brièvement son accès.

Cette version est réservée au propriétaire et à des références internes non personnelles. Elle ne comporte pas encore de comptes vendeurs, de rôles multiples, de MFA/récupération autonome, de téléversement de justificatifs, de traitement des paiements, d'intégration transporteur ou de gestion complète des données clients. Les pièces d'identité et données de paiement ne doivent pas être saisies dans les notes. Les modifications de fournisseur ne doivent être réalisées que par l'administrateur responsable du contrôle.

Les dossiers n'envoient pas de messages au client : « devis envoyé » doit être sélectionné après un envoi réel par un autre canal. Un devis envoyé conserve le prix produit au moment de sa saisie, mais n'est ni un contrat, ni une réservation. Les nouveaux dossiers s'ajoutent ; l'interface permet leur annulation. Aucune commande client n'est reçue automatiquement à ce stade.

## Vérification locale sans serveur réseau

`python3 -m unittest discover -s backend -v`

Les tests couvrent l'authentification, CSRF, contrôle des concepts, validation des fournisseurs, stocks, concurrence produit, persistance, dossiers sans paiement, limitation de connexion et absence de fichiers privés servis par l'application. Gunicorn et le déploiement distant restent à vérifier après accord de création.
