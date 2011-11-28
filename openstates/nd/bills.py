from datetime import datetime
import lxml.html
from billy.scrape import NoDataForPeriod, ScrapeError
from billy.scrape.bills import Bill, BillScraper
from billy.scrape.votes import Vote

_categorizers = (
    ('Amendment adopted', 'amendment:passed'),
    ('Amendment failed', 'amendment:failed'),
    ('Amendment proposed', 'amendment:introduced'),
    ('Divided committee report', 'committee:passed'),
    ('Introduced, first reading', ['bill:introduced', 'bill:reading:1']),
    ('Reported back amended, do not pass', 'committee:passed:unfavorable'),
    ('Reported back amended, do pass', 'committee:passed:favorable'),
    ('Reported back amended, without recommendation', 'committee:passed'),
    ('Reported back, do not pass', 'committee:passed:unfavorable'),
    ('Reported back, do pass', 'committee:passed:favorable'),
    ('Rereferred', 'committee:referred'),
    ('Recieved from House', 'bill:introduced'),
    ('Recieved from Senate', 'bill:introduced'),
    ('Second reading, adopted', ['bill:passed', 'bill:reading:2']),
    ('Second reading, failed', ['bill:failed', 'bill:reading:2']),
    ('Second reading, passed', ['bill:passed', 'bill:reading:2']),
    ('Sent to Governor', 'governor:received'),
    ('Signed by Governor, but item veto', 'governor:vetoed:line-item'),
    ('Signed by Governor', 'governor:signed'),
    ('Withdranw from further consideration', 'bill:withdrawn'),
)

def categorize_action(action):
    for prefix, types in _categorizers:
        if action.startswith(prefix):
            return types
    return 'other'

class NDBillScraper(BillScraper):
    """
    Scrapes available legislative information from the website of the North
    Dakota legislature and stores it in the openstates  backend.
    """
    state = 'nd'
    site_root = 'http://www.legis.nd.gov'

    def scrape(self, chamber, term):
        self.validate_term(term, latest_only=True)

        #determining the start year of the term
        start_year = ((int(term) - 62)*2) + 2011

        # URL building
        if chamber == 'upper':
            url_chamber_name = 'senate'
            norm_chamber_name = 'Senate'
            chamber_letter = 'S'
        else:
            url_chamber_name = 'house'
            norm_chamber_name = 'House'
            chamber_letter = 'H'

        assembly_url = '/assembly/%s-%s' % (term, start_year)

        chamber_url = '/bill-text/%s-bill.html' % (url_chamber_name)

        bill_list_url = self.site_root + assembly_url + chamber_url

        with self.urlopen(bill_list_url) as html:
            list_page = lxml.html.fromstring(html)
            # connects bill_num with bill details page
            bills_url_dict = {}
            #connects bill_num with bills to be accessed later.
            bills_id_dict = {}
            title = ''
            for bills in list_page.xpath('/html/body/table[3]/tr/th/a'):
                bill_num = bills.text
                bill_url = bill_list_url[0:-26] + '/' + bills.attrib['href'][2:len(bills.attrib['href'])]
                bill_prefix, bill_type = self.bill_type_info(bill_num)
                bill_id = chamber_letter + bill_prefix + bill_num
                bill = Bill(term, chamber, bill_id, title, type=bill_type)

                #versions
                versions_url = self.site_root + assembly_url + '//bill-index/bi' + bill_num + '.html'

                #sources
                bill.add_source(bill_url)
                bill.add_source(bill_list_url)

                #storing bills to be accessed
                bills_url_dict[bill_num] = bill_url
                bills_id_dict[bill_num] = bill

            #bill details page
            for bill_keys in bills_url_dict.keys():
                url = bills_url_dict[bill_keys]
                curr_bill = bills_id_dict[bill_keys]
                with self.urlopen(url) as bill_html:
                    bill_page = lxml.html.fromstring(bill_html)
                    for bill_info in bill_page.xpath('/html/body/table[4]/tr/td'):
                        info = bill_info.text

                        #Sponsors
                        if "Introduced" in info:
                            if ('Rep' in info) or ('Sen' in info):
                                rep = info[14:17]
                                info = info[18:len(info)]
                                sponsors = info.split(',')
                            else:
                                sponsors = [info[13: len(info)]]
                                rep = ''
                            for sponsor in sponsors:
                                if sponsor == sponsors[0]:
                                    sponsor_type = 'primary'
                                else:
                                    sponsor_type = 'cosponsor'
                                curr_bill.add_sponsor(sponsor_type,
                                                      sponsor.strip())
                        else:
                            #title
                            title = info.strip()
                            curr_bill["title"] = title

                    #actions
                    last_date = datetime
                    actor = ''
                    action_num = len(bill_page.xpath('/html/body/table[5]//tr'))
                    for actions in range(2, action_num, 2):
                        path = '//table[5]/tr[%s]/' % (actions)
                        action =  bill_page.xpath(path + 'td[4]')[0].text

                        raw_actor = bill_page.xpath(path + 'td[2]')[0].text
                        if not raw_actor:
                            pass
                        elif raw_actor.strip() == 'Senate':
                            actor = 'upper'
                        else:
                            actor = 'lower'

                        action_date = bill_page.xpath(path + 'th')[0].text.strip() + '/' + str(start_year)
                        if action_date == ('/' + str(start_year)):
                            action_date = last_date
                        else:
                            action_date = datetime.strptime(action_date, '%m/%d/%Y')
                        last_date = action_date

                        atype = categorize_action(action)
                        curr_bill.add_action(actor, action, action_date, atype)


                        #votes
                        if "yeas" in action:
                            yes_count = int(action.split()[action.split().index('yeas')+1])
                            no_count = action.split()[action.split().index('nays')+1]
                            no_count = int(no_count[0:-1]) if ',' in no_count else int(no_count)
                            passed = True if yes_count > no_count else False
                            vote_type = self.vote_type_info(action)

                            vote = Vote(actor, action_date, action, passed, yes_count, no_count, 0, vote_type)
                            curr_bill.add_vote(vote)

                        #document within actions
                        doc_num_pos = len(bill_page.xpath(path + 'td'))
                        if doc_num_pos >5:
                            doc_name = bill_page.xpath(path + 'td[6]/a')[0].attrib['href']
                            doc_url = url[0: url.find('bill')].replace('///', '/') + doc_name[3:len(doc_name)]



                #versions
                versions_url = self.site_root + assembly_url + '//bill-index/bi' + bill_num + '.html'
                with self.urlopen(versions_url) as versions_page:
                    versions_page = lxml.html.fromstring(versions_page)
                    version_count = 2
                    for versions in versions_page.xpath('//table[4]//tr/td/a'):
                       version = versions.attrib['href'][2:len(versions.attrib['href'])]
                       version = self.site_root + assembly_url + version
                       version_name = versions.xpath('//table[4]//tr['+str(version_count)+']/td[4]')[0].text
                       version_count += 2
                       curr_bill.add_version(version_name, version)
                curr_bill.add_source(versions_url)

                self.save_bill(curr_bill)

    #Returns action type
    def vote_type_info(self, action):
        if "Second reading" in action:
            vote_type = 'reading:2'
        elif "reading" in action:
            vote_type = 'reading:1'
        elif "Override" in action:
            vote_type = 'veto_override'
        elif "Amendment" in action:
            vote_type = 'amendment'
        else:
            vote_type = 'other'
        return vote_type

    #Returns bill type
    def bill_type_info(self, bill_num):
        bill_num = int(bill_num)
        if 1000 < bill_num < 3000:
            return 'B', 'bill'
        elif 3000 < bill_num < 5000:
            return 'CR', 'concurrent resolution'
        elif 5000 < bill_num < 7000:
            return 'R', 'resolution'
        elif 7000 < bill_num < 9000:
            return 'MR', 'memorial'
