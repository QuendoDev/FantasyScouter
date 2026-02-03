# test_schedule.py
import logging
from src.scrapers.ff_schedule_scraper import FFScheduleScraper

# 1. Configurar Logger básico para ver la salida en consola
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


def run_test():
    print("--- INICIANDO PRUEBA DE CALENDARIO ---")

    # 2. Simular tu Team Map (El ID es la clave crítica)
    # Estos IDs (30, 14, 9, 3) son ejemplos sacados de FF.
    # El scraper usará estos datos si coinciden con las imágenes de la web.
    dummy_team_map = {
        30: {"name": "Girona FC", "slug": "girona-fc", "ff_id": 30},
        14: {"name": "Rayo Vallecano", "slug": "rayo-vallecano", "ff_id": 14},
        15: {"name": "Real Madrid", "slug": "real-madrid", "ff_id": 15},
        3: {"name": "FC Barcelona", "slug": "fc-barcelona", "ff_id": 3}
    }

    # 3. Instanciar el Scraper
    scraper = FFScheduleScraper()

    # 4. Ejecutar el scrapeo LIVE (irá a futbolfantasy.com)
    matches = scraper.scrape(dummy_team_map)

    # 5. Imprimir resultados de muestra
    print("\n--- RESULTADOS ---")
    print(f"Total partidos encontrados: {len(matches)}")

    if matches:
        print("\nEjemplo de los primeros 3 partidos:")
        for m in matches[:3]:
            home = m['home_team'].get('name', 'Unknown')
            away = m['away_team'].get('name', 'Unknown')
            print(f"Jornada {m['jornada']}: {home} vs {away} [{m['score']}] - Terminado: {m['is_finished']}")
    else:
        print("❌ No se encontraron partidos. Revisa los logs.")


if __name__ == "__main__":
    run_test()